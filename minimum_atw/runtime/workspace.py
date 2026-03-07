from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
from biotite.structure.io import load_structure

from ..core.config import Config
from ..plugins.base import Context
from ..core.tables import MANIFEST_COLS, TABLE_NAMES, TABLE_SUFFIX, empty_tables, prefix_row, read_frame


PREPARED_DIRNAME = "_prepared"
PREPARED_STRUCTURES_DIRNAME = "structures"
PREPARED_MANIFEST_NAME = "prepared_manifest.parquet"
PLUGINS_DIRNAME = "_plugins"
RUN_METADATA_NAME = "run_metadata.json"
DATASET_METADATA_NAME = "dataset_metadata.json"
FINAL_OUTPUT_FILES = [f"{table_name}{TABLE_SUFFIX}" for table_name in TABLE_NAMES] + [
    f"plugin_status{TABLE_SUFFIX}",
    f"bad_files{TABLE_SUFFIX}",
    RUN_METADATA_NAME,
    DATASET_METADATA_NAME,
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
    """Create a Context from a structure file.
    
    Args:
        source_path: Original source PDB/CIF file path (for provenance tracking).
            This is recorded in the context and database rows.
        structure_path: Actual file to load (may be same as source_path or a cached prepared file).
            If keep_prepared_structures=True, this may point to a cached prepared structure.
            If keep_prepared_structures=False, this equals source_path (load each time).
        cfg: Config with assembly_id and role mappings
        
    Returns:
        Context with loaded AtomArray and role views built from cfg
    """
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

    for left_role, right_role in ctx.config.interface_pairs_for_outputs():
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
    tables: Any,
    status_rows: Any,
) -> bool:
    def add_status(row: dict[str, Any]) -> None:
        if hasattr(status_rows, "add"):
            status_rows.add(row)
            return
        status_rows.append(row)

    def add_table_row(table_name: str, row: dict[str, Any]) -> None:
        if hasattr(tables, "add"):
            tables.add(table_name, row)
            return
        tables[table_name].append(row)

    available, message = unit.available(ctx) if hasattr(unit, "available") else (True, "")
    if not available:
        add_status(
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
            add_table_row(table, prefix_row(raw, unit.prefix))
        add_status(
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
        add_status(
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
    """Load the prepared manifest, with checkpoint fallback.

    Normally the manifest is stored as a Parquet file. When the user enables
    checkpointing, rows are also appended to a JSONL file (`manifest_checkpoint.jsonl`)
    as each structure is prepared. If the Parquet manifest is missing (for
    example, because a run crashed before it could be written), this helper will
    read the JSONL log instead so downstream stages can start immediately.
    """
    manifest_path = prepared_manifest_path(out_dir)
    if manifest_path.exists():
        manifest = read_frame(manifest_path, MANIFEST_COLS)
    else:
        # fallback to JSON line log used during checkpointing
        log_path = prepared_dir(out_dir) / "manifest_checkpoint.jsonl"
        if not log_path.exists():
            raise FileNotFoundError(f"Prepared outputs not found: {prepared_dir(out_dir)}")
        import json

        records: list[dict[str, str]] = []
        with log_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        import pandas as pd

        manifest = pd.DataFrame(records)

    if manifest.duplicated(["path"]).any():
        raise ValueError("Prepared manifest contains duplicate source paths")
    return manifest
