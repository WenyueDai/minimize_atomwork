from __future__ import annotations

import os
import shutil
import string
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from biotite.structure.io import save_structure

from ....base import Context, InterfacePlugin


ROSETTA_CHAIN_IDS = tuple(string.ascii_uppercase + string.ascii_lowercase + string.digits)


def _existing_path(path: str | os.PathLike[str] | None) -> str | None:
    if not path:
        return None
    resolved = Path(path)
    if resolved.exists():
        return str(resolved)
    return None


def _candidate_bin_dirs(config: Any | None = None, executable: str | None = None) -> list[Path]:
    dirs: list[Path] = []

    configured_executable = _existing_path(getattr(config, "rosetta_executable", None))
    if configured_executable:
        dirs.append(Path(configured_executable).resolve().parent)
    if executable:
        dirs.append(Path(executable).resolve().parent)

    env_bin = os.environ.get("ROSETTA_BIN") or os.environ.get("ROSETTA3_BIN")
    if env_bin:
        dirs.append(Path(env_bin))

    unique: list[Path] = []
    seen: set[Path] = set()
    for directory in dirs:
        resolved = directory.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _resolve_executable(config: Any | None = None) -> str | None:
    # Search order:
    # 1. explicit config path
    # 2. explicit env var
    # 3. Rosetta bin directories from config/env
    # 4. PATH lookup for common executable names
    configured = _existing_path(getattr(config, "rosetta_executable", None))
    if configured:
        return configured

    env_explicit = _existing_path(os.environ.get("ROSETTA_INTERFACE_ANALYZER"))
    if env_explicit:
        return env_explicit

    for bin_path in _candidate_bin_dirs(config):
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


def _resolve_score_jd2_executable(config: Any | None = None) -> str | None:
    configured = _existing_path(getattr(config, "rosetta_score_jd2_executable", None))
    if configured:
        return configured

    env_explicit = _existing_path(os.environ.get("ROSETTA_SCORE_JD2"))
    if env_explicit:
        return env_explicit

    interface_executable = _resolve_executable(config)
    for bin_path in _candidate_bin_dirs(config, executable=interface_executable):
        candidates = (
            bin_path / "score_jd2.static.linuxgccrelease",
            bin_path / "score_jd2.linuxgccrelease",
            bin_path / "score_jd2.default.linuxgccrelease",
        )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    for name in (
        "score_jd2.static.linuxgccrelease",
        "score_jd2.linuxgccrelease",
        "score_jd2.default.linuxgccrelease",
    ):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def _resolve_database(executable: str | None, config: Any | None = None) -> str | None:
    # Rosetta needs its database in addition to the executable. Try an explicit
    # env var first, then infer a standard install layout from the binary path.
    configured = _existing_path(getattr(config, "rosetta_database", None))
    if configured:
        return configured

    env_db = _existing_path(os.environ.get("ROSETTA_DATABASE"))
    if env_db:
        return env_db
    if not executable:
        return None

    exe_path = Path(executable).resolve()
    candidates: list[Path] = []
    for parent_index in (2, 3):
        if len(exe_path.parents) > parent_index:
            candidates.append(exe_path.parents[parent_index] / "database")
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _bool_string(value: bool) -> str:
    return "true" if value else "false"


def _build_interface_analyzer_command(
    executable: str,
    database: str,
    input_path: Path,
    score_path: Path,
    fixedchains: list[str],
    config: Any,
) -> list[str]:
    pack_input = bool(getattr(config, "rosetta_pack_input", True))
    pack_separated = bool(getattr(config, "rosetta_pack_separated", True)) if pack_input else False
    compute_packstat = bool(getattr(config, "rosetta_compute_packstat", True))

    command = [
        executable,
        "-database",
        database,
        "-in:file:s",
        str(input_path),
        "-fixedchains",
        *fixedchains,
        "-use_input_sc",
        "-pack_input",
        _bool_string(pack_input),
        "-pack_separated",
        _bool_string(pack_separated),
        "-compute_packstat",
        _bool_string(compute_packstat),
        "-add_regular_scores_to_scorefile",
        _bool_string(getattr(config, "rosetta_add_regular_scores_to_scorefile", True)),
        "-atomic_burial_cutoff",
        str(getattr(config, "rosetta_atomic_burial_cutoff", 0.01)),
        "-sasa_calculator_probe_radius",
        str(getattr(config, "rosetta_sasa_calculator_probe_radius", 1.4)),
        "-pose_metrics::interface_cutoff",
        str(getattr(config, "rosetta_interface_cutoff", 8.0)),
        "-out:file:score_only",
        str(score_path),
        "-mute",
        "all",
    ]
    oversample = getattr(config, "rosetta_packstat_oversample", None)
    if oversample is not None:
        command.extend(["-packstat::oversample", str(oversample)])
    return command


def _build_score_jd2_command(
    executable: str,
    database: str,
    input_path: Path,
    output_dir: Path,
) -> list[str]:
    return [
        executable,
        "-database",
        database,
        "-in:file:s",
        str(input_path),
        "-no_optH",
        "false",
        "-ignore_unrecognized_res",
        "-out:pdb",
        "-out:path:all",
        str(output_dir),
        "-mute",
        "all",
    ]


def _preprocess_input_with_score_jd2(
    *,
    score_jd2_executable: str,
    database: str,
    input_path: Path,
    tmp_path: Path,
) -> Path:
    output_dir = tmp_path / "score_jd2"
    output_dir.mkdir(parents=True, exist_ok=True)
    command = _build_score_jd2_command(score_jd2_executable, database, input_path, output_dir)
    subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
    )
    outputs = sorted(output_dir.glob("*.pdb"))
    if len(outputs) != 1:
        raise RuntimeError(
            f"score_jd2 expected exactly one preprocessed PDB, found {len(outputs)} in {output_dir}"
        )
    return outputs[0]


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
        "dG_separated/dSASAx100": "interface_dg_separated_per_dsasa_x100",
        "dSASA_int": "interface_dsasa",
        "dSASA_hphobic": "interface_dsasa_hydrophobic",
        "dSASA_polar": "interface_dsasa_polar",
        "packstat": "interface_packstat",
        "sc_value": "interface_sc_value",
        "dG_cross": "interface_dg_cross",
        "dG_cross/dSASAx100": "interface_dg_cross_per_dsasa_x100",
        "cen_dG": "interface_cen_dg",
        "delta_unsatHbonds": "interface_delta_unsat_hbonds",
        "hbonds_int": "interface_hbonds",
        "nres_int": "interface_nres",
        "per_residue_energy_int": "interface_per_residue_energy",
        "side1_score": "interface_side1_score",
        "side2_score": "interface_side2_score",
        "nres_all": "complex_nres",
        "side1_normalized": "interface_side1_normalized",
        "side2_normalized": "interface_side2_normalized",
        "complex_normalized": "complex_normalized",
        "hbond_E_fraction": "interface_hbond_e_fraction",
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
        if out_key in {"interface_delta_unsat_hbonds", "interface_hbonds", "interface_nres", "complex_nres"}:
            parsed[out_key] = int(round(num))
        else:
            parsed[out_key] = num
    return parsed


def _selected_chain_arrays(
    ctx: Context,
    *,
    role_name: str | None,
    chain_ids: list[str],
):
    selected_chain_ids = list(ctx.role_map.get(role_name, ())) if role_name is not None else list(chain_ids)
    if not selected_chain_ids:
        return None

    arrays = []
    for chain_id in selected_chain_ids:
        chain_atoms = ctx.chains.get(chain_id)
        if chain_atoms is None or len(chain_atoms) == 0:
            return None
        arrays.append(chain_atoms)
    return selected_chain_ids, arrays


def _build_fixedchains_pose(left_arrays, right_arrays):
    total_chains = len(left_arrays) + len(right_arrays)
    if total_chains > len(ROSETTA_CHAIN_IDS):
        raise ValueError(f"Rosetta target has too many chains for PDB chain remapping: {total_chains}")

    import biotite.structure as struc

    renamed_arrays = []
    fixedchains: list[str] = []
    chain_index = 0

    for chain_atoms in left_arrays:
        renamed = chain_atoms.copy()
        renamed.chain_id[:] = ROSETTA_CHAIN_IDS[chain_index]
        fixedchains.append(ROSETTA_CHAIN_IDS[chain_index])
        renamed_arrays.append(renamed)
        chain_index += 1

    for chain_atoms in right_arrays:
        renamed = chain_atoms.copy()
        renamed.chain_id[:] = ROSETTA_CHAIN_IDS[chain_index]
        renamed_arrays.append(renamed)
        chain_index += 1

    return struc.concatenate(renamed_arrays), fixedchains


def _iter_rosetta_targets(ctx: Context):
    for target in ctx.config.rosetta_targets():
        left_selection = _selected_chain_arrays(
            ctx,
            role_name=target.left_role,
            chain_ids=target.left_chains,
        )
        right_selection = _selected_chain_arrays(
            ctx,
            role_name=target.right_role,
            chain_ids=target.right_chains,
        )
        if left_selection is None or right_selection is None:
            continue
        _, left_arrays = left_selection
        _, right_arrays = right_selection
        yield target, left_arrays, right_arrays


class RosettaInterfaceExamplePlugin(InterfacePlugin):
    name = "rosetta_interface_example"
    prefix = "rosetta"
    execution = "external"
    input_model = "prepared_file"
    execution_mode = "isolated"
    failure_policy = "continue"

    def available(self, ctx: Context) -> tuple[bool, str]:
        executable = _resolve_executable(ctx.config)
        if executable:
            database = _resolve_database(executable, ctx.config)
            if not database:
                return False, "Rosetta database not found"
            if getattr(ctx.config, "rosetta_preprocess_with_score_jd2", False):
                score_jd2_executable = _resolve_score_jd2_executable(ctx.config)
                if not score_jd2_executable:
                    return False, "Rosetta score_jd2 executable not found"
            return True, ""
        return False, "Rosetta InterfaceAnalyzer executable not found"

    def run(self, ctx: Context):
        executable = _resolve_executable(ctx.config)
        if not executable:
            return
        database = _resolve_database(executable, ctx.config)
        if not database:
            return
        score_jd2_executable = None
        if getattr(ctx.config, "rosetta_preprocess_with_score_jd2", False):
            score_jd2_executable = _resolve_score_jd2_executable(ctx.config)
            if not score_jd2_executable:
                return

        for target, left_arrays, right_arrays in _iter_rosetta_targets(ctx):
            try:
                pair_atoms, fixedchains = _build_fixedchains_pose(left_arrays, right_arrays)
                with tempfile.TemporaryDirectory(prefix="minimum_atw_rosetta_cli_") as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    pair_path = tmp_path / f"{target.pair[0]}__{target.pair[1]}.pdb"
                    score_path = tmp_path / "interface.sc"
                    save_structure(pair_path, pair_atoms)

                    rosetta_input_path = pair_path
                    if score_jd2_executable:
                        rosetta_input_path = _preprocess_input_with_score_jd2(
                            score_jd2_executable=score_jd2_executable,
                            database=database,
                            input_path=pair_path,
                            tmp_path=tmp_path,
                        )

                    command = _build_interface_analyzer_command(
                        executable,
                        database,
                        rosetta_input_path,
                        score_path,
                        fixedchains,
                        ctx.config,
                    )
                    subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        check=True,
                    )

                    metrics = _parse_scorefile(score_path)
                    if not metrics:
                        raise RuntimeError(f"Rosetta scorefile missing metrics: {score_path}")

                yield {
                    **self.pair_identity_row(ctx, left_role=target.pair[0], right_role=target.pair[1]),
                    "database_path": database,
                    **metrics,
                }
            except Exception as exc:
                if isinstance(exc, subprocess.CalledProcessError):
                    err = exc.stderr.strip() or exc.stdout.strip() or type(exc).__name__
                else:
                    err = str(exc) or type(exc).__name__
                print(
                    f"[WARN] Rosetta InterfaceAnalyzer failed for {ctx.path} pair {target.pair[0]}__{target.pair[1]}: {err.splitlines()[-1]}"
                )
                continue
