from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
from biotite.structure.io import load_structure

from .config import Config
from .plugins.base import Context
from .tables import MANIFEST_COLS, TABLE_NAMES, TABLE_SUFFIX, empty_tables, prefix_row, read_frame


PREPARED_DIRNAME = "_prepared"
PREPARED_STRUCTURES_DIRNAME = "structures"
PREPARED_MANIFEST_NAME = "prepared_manifest.parquet"
PLUGINS_DIRNAME = "_plugins"
FINAL_OUTPUT_FILES = [f"{table_name}{TABLE_SUFFIX}" for table_name in TABLE_NAMES] + [
    f"plugin_status{TABLE_SUFFIX}",
    f"bad_files{TABLE_SUFFIX}",
]


def discover_inputs(input_dir: Path) -> list[Path]:
    files = []
    for pattern in ("*.pdb", "*.cif"):
        files.extend(sorted(input_dir.glob(pattern)))
    return files


def chunk_input_paths(paths: list[Path], chunk_size: int) -> list[list[Path]]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")
    return [paths[idx : idx + chunk_size] for idx in range(0, len(paths), chunk_size)]


def chunk_dir_name(index: int) -> str:
    return f"chunk_{index:04d}"


def prepare_chunk_input_dir(chunk_input_dir: Path, chunk_paths: list[Path]) -> None:
    chunk_input_dir.mkdir(parents=True, exist_ok=True)
    for source_path in chunk_paths:
        target_path = chunk_input_dir / source_path.name
        if target_path.exists() or target_path.is_symlink():
            target_path.unlink()
        target_path.symlink_to(source_path.resolve())


def prepare_context(source_path: Path, structure_path: Path, cfg: Config) -> Context:
    aa = load_structure(structure_path)
    ctx = Context(
        path=str(source_path.resolve()),
        assembly_id=cfg.assembly_id,
        aa=aa,
        role_map={name: tuple(chain_ids) for name, chain_ids in cfg.roles.items()},
        config=cfg,
    )
    ctx.rebuild_views()
    return ctx


def base_rows_for_context(ctx: Context) -> dict[str, list[dict[str, Any]]]:
    tables = empty_tables()
    tables["structures"].append({"path": ctx.path, "assembly_id": ctx.assembly_id})

    for chain_id in sorted(ctx.chains):
        tables["chains"].append({"path": ctx.path, "assembly_id": ctx.assembly_id, "chain_id": chain_id})

    for role_name in sorted(ctx.roles):
        tables["roles"].append({"path": ctx.path, "assembly_id": ctx.assembly_id, "role": role_name})

    for left_role, right_role in ctx.config.interface_pairs:
        left = ctx.roles.get(left_role)
        right = ctx.roles.get(right_role)
        if left is None or right is None or len(left) == 0 or len(right) == 0:
            continue
        tables["interfaces"].append(
            {
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "pair": f"{left_role}__{right_role}",
                "role_left": left_role,
                "role_right": right_role,
            }
        )
    return tables


def run_unit(
    ctx: Context,
    unit: Any,
    tables: dict[str, list[dict[str, Any]]],
    status_rows: list[dict[str, Any]],
) -> bool:
    available, message = unit.available(ctx) if hasattr(unit, "available") else (True, "")
    if not available:
        status_rows.append(
            {
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "plugin": unit.name,
                "status": "skipped_preflight",
                "message": message,
            }
        )
        return False

    try:
        emitted = 0
        for raw in unit.run(ctx) or []:
            emitted += 1
            table = raw.get("__table__", getattr(unit, "table", "structures"))
            tables[table].append(prefix_row(raw, unit.prefix))
        status_rows.append(
            {
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "plugin": unit.name,
                "status": "ok",
                "message": f"rows={emitted}",
            }
        )
        return True
    except Exception as exc:
        status_rows.append(
            {
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "plugin": unit.name,
                "status": "failed",
                "message": f"{type(exc).__name__}: {exc}",
            }
        )
        return False


def prepared_dir(out_dir: Path) -> Path:
    return out_dir / PREPARED_DIRNAME


def prepared_structures_dir(out_dir: Path) -> Path:
    return prepared_dir(out_dir) / PREPARED_STRUCTURES_DIRNAME


def prepared_manifest_path(out_dir: Path) -> Path:
    return prepared_dir(out_dir) / PREPARED_MANIFEST_NAME


def plugins_dir(out_dir: Path) -> Path:
    return out_dir / PLUGINS_DIRNAME


def plugin_dir(out_dir: Path, plugin_name: str) -> Path:
    return plugins_dir(out_dir) / plugin_name


def clear_final_outputs(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for filename in FINAL_OUTPUT_FILES:
        path = out_dir / filename
        if path.exists():
            path.unlink()
    analysis_dir = out_dir / "dataset_analysis"
    if analysis_dir.exists():
        shutil.rmtree(analysis_dir)


def copy_final_outputs(source_out_dir: Path, target_out_dir: Path) -> None:
    clear_final_outputs(target_out_dir)
    for filename in FINAL_OUTPUT_FILES:
        source_path = source_out_dir / filename
        if source_path.exists():
            shutil.copy2(source_path, target_out_dir / filename)


def prepared_filename(source_path: Path) -> str:
    digest = hashlib.sha1(str(source_path.resolve()).encode("utf-8")).hexdigest()[:12]
    suffix = source_path.suffix.lower() if source_path.suffix.lower() in {".pdb", ".cif"} else ".pdb"
    return f"{source_path.stem}_{digest}{suffix}"


def load_prepared_manifest(out_dir: Path) -> pd.DataFrame:
    manifest_path = prepared_manifest_path(out_dir)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Prepared outputs not found: {prepared_dir(out_dir)}")
    manifest = read_frame(manifest_path, MANIFEST_COLS)
    if manifest.duplicated(["path"]).any():
        raise ValueError("Prepared manifest contains duplicate source paths")
    return manifest
