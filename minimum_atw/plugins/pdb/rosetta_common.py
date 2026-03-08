from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


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


def resolve_executable(config: Any | None = None) -> str | None:
    """Resolve the Rosetta InterfaceAnalyzer executable."""
    configured = _existing_path(getattr(config, "rosetta_executable", None))
    if configured:
        return configured

    env_explicit = _existing_path(os.environ.get("ROSETTA_INTERFACE_ANALYZER"))
    if env_explicit:
        return env_explicit

    for bin_path in _candidate_bin_dirs(config):
        for name in (
            "InterfaceAnalyzer.static.linuxgccrelease",
            "InterfaceAnalyzer.linuxgccrelease",
            "InterfaceAnalyzer.default.linuxgccrelease",
        ):
            candidate = bin_path / name
            if candidate.exists():
                return str(candidate)

    for name in (
        "InterfaceAnalyzer.static.linuxgccrelease",
        "InterfaceAnalyzer.linuxgccrelease",
        "InterfaceAnalyzer.default.linuxgccrelease",
    ):
        found = shutil.which(name)
        if found:
            return found
    return None


def resolve_score_jd2_executable(config: Any | None = None) -> str | None:
    """Resolve the Rosetta score_jd2 executable."""
    configured = _existing_path(getattr(config, "rosetta_score_jd2_executable", None))
    if configured:
        return configured

    env_explicit = _existing_path(os.environ.get("ROSETTA_SCORE_JD2"))
    if env_explicit:
        return env_explicit

    interface_executable = resolve_executable(config)
    for bin_path in _candidate_bin_dirs(config, executable=interface_executable):
        for name in (
            "score_jd2.static.linuxgccrelease",
            "score_jd2.linuxgccrelease",
            "score_jd2.default.linuxgccrelease",
        ):
            candidate = bin_path / name
            if candidate.exists():
                return str(candidate)

    for name in (
        "score_jd2.static.linuxgccrelease",
        "score_jd2.linuxgccrelease",
        "score_jd2.default.linuxgccrelease",
    ):
        found = shutil.which(name)
        if found:
            return found
    return None


def resolve_relax_executable(config: Any | None = None) -> str | None:
    """Resolve the Rosetta relax executable."""
    configured = _existing_path(getattr(config, "rosetta_relax_executable", None))
    if configured:
        return configured

    env_explicit = _existing_path(os.environ.get("ROSETTA_RELAX"))
    if env_explicit:
        return env_explicit

    interface_executable = resolve_executable(config)
    for bin_path in _candidate_bin_dirs(config, executable=interface_executable):
        for name in (
            "relax.static.linuxgccrelease",
            "relax.linuxgccrelease",
            "relax.default.linuxgccrelease",
        ):
            candidate = bin_path / name
            if candidate.exists():
                return str(candidate)

    for name in (
        "relax.static.linuxgccrelease",
        "relax.linuxgccrelease",
        "relax.default.linuxgccrelease",
    ):
        found = shutil.which(name)
        if found:
            return found
    return None


def resolve_database(executable: str | None, config: Any | None = None) -> str | None:
    """Resolve the Rosetta database directory."""
    configured = _existing_path(getattr(config, "rosetta_database", None))
    if configured:
        return configured

    env_db = _existing_path(os.environ.get("ROSETTA_DATABASE"))
    if env_db:
        return env_db
    if not executable:
        return None

    exe_path = Path(executable).resolve()
    for parent_index in (2, 3):
        if len(exe_path.parents) > parent_index:
            candidate = exe_path.parents[parent_index] / "database"
            if candidate.exists():
                return str(candidate)
    return None


def run_score_jd2(
    *,
    executable: str,
    database: str,
    input_path: Path,
    score_path: Path,
    output_pdb_dir: Path | None = None,
) -> None:
    """Run score_jd2 for scoring (and optionally structure output)."""
    command = [
        executable,
        "-database", database,
        "-in:file:s", str(input_path),
        "-no_optH", "false",
        "-ignore_unrecognized_res",
        "-out:file:scorefile", str(score_path),
    ]
    if output_pdb_dir is not None:
        command += ["-out:pdb", "-out:path:all", str(output_pdb_dir)]
    else:
        command += ["-out:nooutput"]
    command += ["-mute", "all"]
    subprocess.run(command, capture_output=True, text=True, check=True)


def run_relax(
    *,
    executable: str,
    database: str,
    input_path: Path,
    output_dir: Path,
    backbone_move: bool,
) -> Path:
    """Run Rosetta fast relax (or repack-only when backbone_move=False).

    Returns the path to the relaxed output PDB.
    """
    command = [
        executable,
        "-database", database,
        "-in:file:s", str(input_path),
        "-relax:fast",
        "-relax:bb_move", "true" if backbone_move else "false",
        "-ignore_unrecognized_res",
        "-nstruct", "1",
        "-out:pdb",
        "-out:path:all", str(output_dir),
        "-mute", "all",
    ]
    subprocess.run(command, capture_output=True, text=True, check=True)
    outputs = sorted(output_dir.glob("*.pdb"))
    if not outputs:
        raise RuntimeError(f"relax produced no output PDB in {output_dir}")
    return outputs[0]


def parse_score_jd2_scorefile(score_path: Path) -> dict[str, float | int]:
    """Parse a score_jd2 scorefile and return all numeric energy terms."""
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

    integer_terms = {"nres_all", "nres_int"}
    parsed: dict[str, float | int] = {}
    for key, val in zip(keys, vals):
        if key == "description":
            continue
        try:
            num = float(val)
        except Exception:
            continue
        parsed[key] = int(round(num)) if key in integer_terms else num
    return parsed
