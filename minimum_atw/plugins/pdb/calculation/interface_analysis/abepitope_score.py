from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from importlib.util import find_spec
from pathlib import Path

import biotite.structure as struc
from biotite.structure.io import save_structure

from ..base import Context, InterfacePlugin


def _runner_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "externals" / "abepitope_runner.py"


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
    resource_class = "heavy"
    execution_mode = "isolated"
    failure_policy = "continue"

    _worker_process: subprocess.Popen[str] | None = None
    _worker_registered: bool = False

    def available(self, _ctx: Context) -> tuple[bool, str]:
        if find_spec("abepitope") is None:
            return False, "abepitope is not installed"
        hmmsearch = _resolve_hmmsearch()
        if not hmmsearch:
            return False, "hmmsearch is not available on PATH; install HMMER"
        return True, ""

    def _worker_env(self) -> dict[str, str]:
        env = dict(os.environ)
        python_bin = str(Path(sys.executable).resolve().parent)
        env["PATH"] = python_bin if not env.get("PATH") else f"{python_bin}:{env['PATH']}"
        return env

    def _shutdown_worker(self) -> None:
        proc = self._worker_process
        if proc is None:
            return
        try:
            if proc.poll() is None and proc.stdin is not None and proc.stdout is not None:
                proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                proc.stdin.flush()
                proc.stdout.readline()
                proc.wait(timeout=2)
        except Exception:
            if proc.poll() is None:
                proc.kill()
        finally:
            self._worker_process = None

    def _get_worker(self) -> subprocess.Popen[str]:
        proc = self._worker_process
        if proc is not None and proc.poll() is None and proc.stdin is not None and proc.stdout is not None:
            return proc

        self._shutdown_worker()
        proc = subprocess.Popen(
            [sys.executable, str(_runner_script_path()), "--worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self._worker_env(),
        )
        self._worker_process = proc
        if not self._worker_registered:
            atexit.register(self._shutdown_worker)
            self._worker_registered = True
        return proc

    def _run_backend(self, pair_path: Path, *, atom_radius: float) -> dict[str, float]:
        proc = self._get_worker()
        if proc.stdin is None or proc.stdout is None:
            return {}

        proc.stdin.write(json.dumps({"structure_path": str(pair_path), "atom_radius": atom_radius}) + "\n")
        proc.stdin.flush()

        payload = proc.stdout.readline().strip()
        if not payload:
            stderr = ""
            if proc.stderr is not None:
                try:
                    stderr = proc.stderr.read().strip()
                except Exception:
                    stderr = ""
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
        return {str(key): float(value) for key, value in metrics.items() if value is not None}

    def run(self, ctx: Context):
        atom_radius = float(getattr(ctx.config, "abepitope_atom_radius", 4.0))
        for left_role, right_role, left, right in self.iter_role_pairs(ctx):
            pair_atoms = struc.concatenate([left, right])
            with tempfile.TemporaryDirectory(prefix="minimum_atw_abepitope_pair_") as tmp_dir:
                pair_path = Path(tmp_dir) / f"{left_role}__{right_role}.pdb"
                save_structure(pair_path, pair_atoms)
                metrics = self._run_backend(pair_path, atom_radius=atom_radius)
            if not metrics:
                continue
            yield {
                **self.pair_identity_row(ctx, left_role=left_role, right_role=right_role),
                "atom_radius": atom_radius,
                **metrics,
            }
