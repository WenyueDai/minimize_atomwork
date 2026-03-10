from __future__ import annotations

import atexit
import hashlib
import io
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import biotite.structure as struc
from biotite.structure.io.pdb import PDBFile

from ....base import Context, InterfacePlugin
from ..._utils import _gpu_scheduling, _resolve_device


_HEAVY_ROLE_HINTS = {"vh", "vhh", "heavy", "heavy_chain", "hc"}
_LIGHT_ROLE_HINTS = {"vl", "light", "light_chain", "lc"}
_ANTIGEN_ROLE_HINTS = {"antigen", "target"}
_ANTIBODY_ROLE_HINTS = _HEAVY_ROLE_HINTS | _LIGHT_ROLE_HINTS | {"antibody", "binder", "scfv"}


def _runner_script_path() -> Path:
    return Path(__file__).resolve().parents[4] / "externals" / "abepitope_runner.py"


def _pair_to_pdb_content(atoms) -> str:
    pdb = PDBFile()
    pdb.set_structure(atoms)
    buf = io.StringIO()
    pdb.write(buf)
    return buf.getvalue()


def _backend_cache_key(pdb_content: str, *, atom_radius: float) -> str:
    payload = f"r:{atom_radius}\n{pdb_content}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _chain_ids(arr) -> list[str]:
    if arr is None or len(arr) == 0:
        return []
    return sorted({str(chain_id) for chain_id in arr.chain_id.astype(str)})


def _role_chain_ids(ctx: Context, role_name: str) -> list[str]:
    return [str(chain_id) for chain_id in getattr(ctx.config, "roles", {}).get(role_name, []) if str(chain_id)]


def _abepitope_chain_hints(
    ctx: Context,
    *,
    left_role: str,
    right_role: str,
    left,
    right,
) -> dict[str, list[str]] | None:
    pair_chain_ids = set(_chain_ids(struc.concatenate([left, right])))
    if not pair_chain_ids:
        return None

    heavy_chain_ids: set[str] = set()
    light_chain_ids: set[str] = set()

    for role_name in getattr(ctx.config, "numbering_roles", []) or []:
        normalized = str(role_name).strip().lower()
        role_chain_ids = set(_role_chain_ids(ctx, str(role_name)))
        if not role_chain_ids:
            continue
        if normalized in _HEAVY_ROLE_HINTS:
            heavy_chain_ids.update(role_chain_ids & pair_chain_ids)
        elif normalized in _LIGHT_ROLE_HINTS:
            light_chain_ids.update(role_chain_ids & pair_chain_ids)

    for role_name, chain_ids in getattr(ctx.config, "roles", {}).items():
        normalized = str(role_name).strip().lower()
        chain_id_set = {str(chain_id) for chain_id in chain_ids if str(chain_id)} & pair_chain_ids
        if not chain_id_set:
            continue
        if normalized in _HEAVY_ROLE_HINTS:
            heavy_chain_ids.update(chain_id_set)
        elif normalized in _LIGHT_ROLE_HINTS:
            light_chain_ids.update(chain_id_set)

    left_chain_ids = set(_chain_ids(left))
    right_chain_ids = set(_chain_ids(right))
    left_name = str(left_role).strip().lower()
    right_name = str(right_role).strip().lower()

    antibody_chain_ids = set(heavy_chain_ids | light_chain_ids)
    antigen_chain_ids = pair_chain_ids - antibody_chain_ids

    if not antibody_chain_ids:
        if left_name in _ANTIBODY_ROLE_HINTS and right_name in _ANTIGEN_ROLE_HINTS:
            antibody_chain_ids = set(left_chain_ids)
            antigen_chain_ids = set(right_chain_ids)
        elif right_name in _ANTIBODY_ROLE_HINTS and left_name in _ANTIGEN_ROLE_HINTS:
            antibody_chain_ids = set(right_chain_ids)
            antigen_chain_ids = set(left_chain_ids)

    if not heavy_chain_ids and not light_chain_ids and len(antibody_chain_ids) == 1:
        heavy_chain_ids = set(antibody_chain_ids)

    if not antigen_chain_ids:
        antigen_chain_ids = pair_chain_ids - set(heavy_chain_ids | light_chain_ids)

    if (not heavy_chain_ids and not light_chain_ids) or not antigen_chain_ids:
        return None

    return {
        "heavy_chain_ids": sorted(heavy_chain_ids),
        "light_chain_ids": sorted(light_chain_ids),
        "antigen_chain_ids": sorted(antigen_chain_ids),
    }


def _resolve_hmmsearch() -> str | None:
    env_bin_candidate = Path(sys.executable).resolve().parent / "hmmsearch"
    if env_bin_candidate.exists() and os.access(env_bin_candidate, os.X_OK):
        return str(env_bin_candidate)
    resolved = shutil.which("hmmsearch")
    if resolved and os.access(resolved, os.X_OK):
        return resolved
    return None


class AbEpiTopeScorePlugin(InterfacePlugin):
    name = "abepitope_score"
    prefix = "abepitope"
    input_model = "hybrid"
    execution_mode = "isolated"
    failure_policy = "continue"

    _worker_process: subprocess.Popen[str] | None = None
    _worker_registered: bool = False
    _worker_stderr_handle = None
    _worker_device: str | None = None
    _metrics_cache: dict[str, dict[str, float]] = {}

    def scheduling(self, cfg: Any | None = None) -> dict[str, Any]:
        return _gpu_scheduling(super().scheduling(cfg), cfg, self.name)

    def available(self, ctx: Context | None) -> tuple[bool, str]:
        try:
            import abepitope  # noqa: F401
        except ImportError as exc:
            return False, f"abepitope is not importable: {exc}"
        if ctx is not None:
            hints = None
            for left_role, right_role, left, right in self.iter_role_pairs(ctx):
                hints = _abepitope_chain_hints(
                    ctx,
                    left_role=left_role,
                    right_role=right_role,
                    left=left,
                    right=right,
                )
                if hints:
                    break
            if hints:
                return True, ""
        hmmsearch = _resolve_hmmsearch()
        if not hmmsearch:
            return False, "hmmsearch is not available on PATH and chain hints could not be derived from roles"
        return True, ""

    def _worker_env(self) -> dict[str, str]:
        env = dict(os.environ)
        python_bin = str(Path(sys.executable).resolve().parent)
        env["PATH"] = python_bin if not env.get("PATH") else f"{python_bin}:{env['PATH']}"
        return env

    def _worker_startup_timeout(self) -> float:
        raw = os.environ.get("MINIMUM_ATW_ABEPITOPE_STARTUP_TIMEOUT_SEC", "").strip()
        if raw:
            try:
                return max(1.0, float(raw))
            except ValueError:
                pass
        return 300.0

    def _worker_request_timeout(self) -> float | None:
        raw = os.environ.get("MINIMUM_ATW_ABEPITOPE_REQUEST_TIMEOUT_SEC", "").strip()
        if not raw:
            return None
        try:
            return max(1.0, float(raw))
        except ValueError:
            return None

    def _read_line(self, stream, *, timeout: float | None) -> str:
        if timeout is None:
            return stream.readline()
        try:
            fileno = stream.fileno()
        except Exception:
            return stream.readline()
        ready, _, _ = select.select([fileno], [], [], timeout)
        if not ready:
            raise TimeoutError(f"Timed out after {timeout:.1f}s waiting for AbEpiTope worker output")
        return stream.readline()

    def _read_worker_stderr(self) -> str:
        handle = self._worker_stderr_handle
        if handle is None:
            return ""
        try:
            handle.flush()
            handle.seek(0)
            data = handle.read().strip()
        except Exception:
            return ""
        if len(data) > 4000:
            return data[-4000:]
        return data

    def _close_worker_stderr(self) -> None:
        handle = self._worker_stderr_handle
        self._worker_stderr_handle = None
        if handle is None:
            return
        try:
            handle.close()
        except Exception:
            pass

    def _shutdown_worker(self) -> None:
        proc = self._worker_process
        if proc is None:
            self._worker_device = None
            self._close_worker_stderr()
            return
        try:
            if proc.poll() is None and proc.stdin is not None and proc.stdout is not None:
                proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                proc.stdin.flush()
                self._read_line(proc.stdout, timeout=2.0)
                proc.wait(timeout=2)
        except Exception:
            if proc.poll() is None:
                proc.kill()
        finally:
            self._worker_process = None
            self._worker_device = None
            self._close_worker_stderr()

    def _get_worker(self, *, device: str) -> subprocess.Popen[str]:
        proc = self._worker_process
        if (
            proc is not None
            and proc.poll() is None
            and proc.stdin is not None
            and proc.stdout is not None
            and self._worker_device == device
        ):
            return proc

        self._shutdown_worker()
        stderr_handle = tempfile.TemporaryFile(mode="w+")
        command = [sys.executable, str(_runner_script_path()), "--worker", "--device", device]
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_handle,
            text=True,
            bufsize=1,
            env=self._worker_env(),
        )
        self._worker_process = proc
        self._worker_stderr_handle = stderr_handle
        self._worker_device = device
        if not self._worker_registered:
            atexit.register(self._shutdown_worker)
            self._worker_registered = True
        try:
            ready_payload = self._read_line(proc.stdout, timeout=self._worker_startup_timeout()).strip()
        except Exception:
            stderr = self._read_worker_stderr()
            self._shutdown_worker()
            raise subprocess.CalledProcessError(
                returncode=proc.returncode if proc.returncode is not None else 1,
                cmd=command,
                stderr=stderr or "AbEpiTope worker failed to start",
            )
        parsed = json.loads(ready_payload) if ready_payload else {}
        if not parsed.get("ok", False) or parsed.get("event") != "ready":
            stderr = self._read_worker_stderr()
            self._shutdown_worker()
            raise subprocess.CalledProcessError(
                returncode=proc.returncode if proc.returncode is not None else 1,
                cmd=command,
                stderr=stderr or str(parsed or "AbEpiTope worker failed to initialize"),
            )
        return proc

    def _run_backend(
        self,
        pdb_content: str,
        *,
        seq_hash: str,
        atom_radius: float,
        device: str,
        chain_hints: dict[str, list[str]] | None = None,
    ) -> dict[str, float]:
        cached = self._metrics_cache.get(seq_hash)
        if cached is not None:
            return dict(cached)
        proc = self._get_worker(device=device)
        if proc.stdin is None or proc.stdout is None:
            return {}

        proc.stdin.write(
            json.dumps(
                {
                    "pdb_content": pdb_content,
                    "seq_hash": seq_hash,
                    "atom_radius": atom_radius,
                    "chain_hints": chain_hints,
                }
            )
            + "\n"
        )
        proc.stdin.flush()

        payload = self._read_line(proc.stdout, timeout=self._worker_request_timeout()).strip()
        if not payload:
            stderr = self._read_worker_stderr()
            self._shutdown_worker()
            raise subprocess.CalledProcessError(
                returncode=proc.returncode if proc.returncode is not None else 1,
                cmd=[sys.executable, str(_runner_script_path()), "--worker"],
                stderr=stderr,
            )

        parsed = json.loads(payload)
        if not parsed.get("ok", False):
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=[sys.executable, str(_runner_script_path()), "--worker"],
                stderr=str(parsed.get("error", "unknown error")),
            )

        metrics = parsed.get("metrics", {})
        if not isinstance(metrics, dict):
            return {}
        normalized = {str(key): float(value) for key, value in metrics.items() if value is not None}
        self._metrics_cache[seq_hash] = dict(normalized)
        return normalized

    def run(self, ctx: Context):
        atom_radius = float(getattr(ctx.config, "abepitope_atom_radius", 4.0))
        params = self.plugin_params(ctx)
        device = _resolve_device(str(params.get("device", "auto")))
        for left_role, right_role, left, right in self.iter_role_pairs(ctx):
            pair_atoms = struc.concatenate([left, right])
            pdb_content = _pair_to_pdb_content(pair_atoms)
            seq_key = _backend_cache_key(pdb_content, atom_radius=atom_radius)
            chain_hints = _abepitope_chain_hints(
                ctx,
                left_role=left_role,
                right_role=right_role,
                left=left,
                right=right,
            )
            metrics = self._run_backend(
                pdb_content,
                seq_hash=seq_key,
                atom_radius=atom_radius,
                device=device,
                chain_hints=chain_hints,
            )
            if not metrics:
                continue
            yield {
                **self.pair_identity_row(ctx, left_role=left_role, right_role=right_role),
                "atom_radius": atom_radius,
                **metrics,
            }
