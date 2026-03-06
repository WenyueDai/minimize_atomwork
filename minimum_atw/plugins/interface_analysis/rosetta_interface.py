from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from biotite.structure.io import save_structure

from ..base import Context, InterfacePlugin


def _resolve_executable() -> str | None:
    # Search order:
    # 1. explicit env var
    # 2. Rosetta bin directory env var
    # 3. PATH lookup for common executable names
    env_explicit = os.environ.get("ROSETTA_INTERFACE_ANALYZER")
    if env_explicit and Path(env_explicit).exists():
        return env_explicit

    env_bin = os.environ.get("ROSETTA_BIN") or os.environ.get("ROSETTA3_BIN")
    if env_bin:
        bin_path = Path(env_bin)
        candidates = (
            bin_path / "InterfaceAnalyzer.static.linuxgccrelease",
            bin_path / "InterfaceAnalyzer.linuxgccrelease",
            bin_path / "InterfaceAnalyzer.default.linuxgccrelease",
        )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    for name in (
        "InterfaceAnalyzer.static.linuxgccrelease",
        "InterfaceAnalyzer.linuxgccrelease",
        "InterfaceAnalyzer.default.linuxgccrelease",
    ):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def _resolve_database(executable: str | None) -> str | None:
    # Rosetta needs its database in addition to the executable. Try an explicit
    # env var first, then infer a standard install layout from the binary path.
    env_db = os.environ.get("ROSETTA_DATABASE")
    if env_db and Path(env_db).exists():
        return env_db
    if not executable:
        return None

    exe_path = Path(executable).resolve()
    candidates = [
        exe_path.parents[2] / "database",
        exe_path.parents[3] / "database" if len(exe_path.parents) > 3 else None,
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate)
    return None


def _parse_scorefile(score_path: Path) -> dict[str, float | int]:
    # Rosetta scorefiles contain a header row and one or more SCORE rows; the
    # final SCORE row is the actual result we want.
    if not score_path.exists():
        return {}

    lines = [line.strip() for line in score_path.read_text().splitlines() if line.strip()]
    header = next((line for line in lines if line.startswith("SCORE:") and "description" in line), None)
    values = None
    for line in reversed(lines):
        if line.startswith("SCORE:") and "description" not in line:
            values = line
            break
    if header is None or values is None:
        return {}

    keys = header.split()[1:]
    vals = values.split()[1:]
    if len(keys) != len(vals):
        return {}

    wanted = {
        # Map Rosetta's native column names to the output schema used by this
        # package.
        "interface_dG": "interface_dg",
        "dG_separated": "interface_dg_separated",
        "dSASA_int": "interface_dsasa",
        "dSASA_hphobic": "interface_dsasa_hydrophobic",
        "dSASA_polar": "interface_dsasa_polar",
        "packstat": "interface_packstat",
        "sc_value": "interface_sc_value",
        "delta_unsatHbonds": "interface_delta_unsat_hbonds",
        "hbonds_int": "interface_hbonds",
        "nres_int": "interface_nres",
    }
    parsed: dict[str, float | int] = {}
    for key, value in zip(keys, vals):
        out_key = wanted.get(key)
        if out_key is None:
            continue
        try:
            num = float(value)
        except Exception:
            continue
        if out_key in {"interface_delta_unsat_hbonds", "interface_hbonds", "interface_nres"}:
            parsed[out_key] = int(round(num))
        else:
            parsed[out_key] = num
    return parsed


def _renamed_pair_atoms(left_atoms, right_atoms):
    """Rename chains to A/B for Rosetta InterfaceAnalyzer compatibility.
    
    Rosetta InterfaceAnalyzer uses the `-interface A_B` flag to specify a
    two-group analysis. This function handles both:
    - Simple two-chain interfaces (single chain per role)
    - Multi-chain interfaces (multiple chains within a single role)
    
    By renaming all chains in a role to the same letter (A or B), we standardize
    multi-chain complexes into the two-group format that Rosetta expects, without
    needing the more complex `-fixedchains` syntax.
    """
    import biotite.structure as struc
    
    # Copy and rename chains to A/B format
    left_copy = left_atoms.copy()
    right_copy = right_atoms.copy()
    left_copy.chain_id[:] = "A"
    right_copy.chain_id[:] = "B"
    
    return struc.concatenate([left_copy, right_copy])


class RosettaInterfaceExamplePlugin(InterfacePlugin):
    name = "rosetta_interface_example"
    prefix = "rosetta"
    execution = "external"

    def available(self, ctx: Context) -> tuple[bool, str]:
        executable = _resolve_executable()
        if executable:
            database = _resolve_database(executable)
            if database:
                return True, ""
            return False, "Rosetta database not found"
        return False, "Rosetta InterfaceAnalyzer executable not found"

    def run(self, ctx: Context):
        executable = _resolve_executable()
        if not executable:
            return
        database = _resolve_database(executable)
        if not database:
            return

        for left_role, right_role, left, right in self.iter_role_pairs(ctx):
            # Rosetta InterfaceAnalyzer uses -interface A_B to specify a two-group
            # analysis. We rename all chains in the left role to A and right role
            # to B. This handles both simple two-chain and complex multi-chain
            # interfaces uniformly: (H+L chains) vs (A chain) becomes A_B analysis.
            pair_atoms = _renamed_pair_atoms(left, right)
            with tempfile.TemporaryDirectory(prefix="minimum_atw_rosetta_cli_") as tmp_dir:
                tmp_path = Path(tmp_dir)
                pair_path = tmp_path / f"{left_role}__{right_role}.pdb"
                score_path = tmp_path / "interface.sc"
                save_structure(pair_path, pair_atoms)

                command = [
                    # Rosetta CLI invocation: load one pose, analyze interface
                    # A_B, and write scores to a dedicated scorefile.
                    executable,
                    "-database",
                    database,
                    "-in:file:s",
                    str(pair_path),
                    "-interface",
                    "A_B",
                    "-pack_separated",
                    "true",
                    "-compute_packstat",
                    "true",
                    "-out:file:score_only",
                    str(score_path),
                    "-mute",
                    "all",
                ]
                try:
                    subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                except subprocess.CalledProcessError as exc:
                    err = exc.stderr.strip() or exc.stdout.strip() or type(exc).__name__
                    print(
                        f"[WARN] Rosetta InterfaceAnalyzer failed for {ctx.path} pair {left_role}__{right_role}: {err.splitlines()[-1]}"
                    )
                    continue

                metrics = _parse_scorefile(score_path)
                if not metrics:
                    continue

                yield {
                    **self.pair_identity_row(ctx, left_role=left_role, right_role=right_role),
                    "database_path": database,
                    **metrics,
                }
