from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
from biotite.structure.io import load_structure

from ..core.config import Config
from ..core.output_files import (
    BAD_OUTPUT_NAME,
    DATASET_METADATA_NAME,
    PLUGIN_STATUS_OUTPUT_NAME,
    RUN_METADATA_NAME,
    pdb_output_path,
    output_files_from_config,
    output_files_from_metadata,
    read_output_metadata,
)
from ..plugins.base import Context
from ..core.tables import (
    MANIFEST_COLS,
    PDB_TABLE_NAME,
    TABLE_SUFFIX,
    empty_pdb_rows,
    prefix_row,
    read_frame,
    read_pdb_table,
    write_pdb_table,
)


PREPARED_DIRNAME = "_prepared"
PREPARED_STRUCTURES_DIRNAME = "structures"
PREPARED_MANIFEST_NAME = "prepared_manifest.parquet"
PLUGINS_DIRNAME = "_plugins"
SUPERIMPOSED_STRUCTURES_DIRNAME = "superimposed_structures"
OPTIONAL_DEBUG_OUTPUT_FILES = [PLUGIN_STATUS_OUTPUT_NAME]


def final_output_files(*, cfg: Config | None = None, metadata: dict[str, Any] | None = None) -> list[str]:
    output_files = output_files_from_config(cfg) if cfg is not None else output_files_from_metadata(metadata)
    return [
        output_files["pdb"],
        output_files["dataset"],
        BAD_OUTPUT_NAME,
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
    source_stat = source_path.stat()
    source_format = source_path.suffix.lower().lstrip(".")
    loaded_format = structure_path.suffix.lower().lstrip(".")
    metadata = {
        "source": {
            "path": str(source_path.resolve()),
            "name": source_path.name,
            "format": source_format,
            "size_bytes": int(source_stat.st_size),
            "mtime_ns": int(source_stat.st_mtime_ns),
        },
        "loaded": {
            "path": str(structure_path.resolve()),
            "format": loaded_format,
        },
        "structure": {
            "n_atoms_loaded": int(len(aa)),
            "n_chains_loaded": int(len({str(chain_id) for chain_id in aa.chain_id})) if len(aa) else 0,
        },
    }
    ctx = Context(
        path=str(source_path.resolve()),
        assembly_id=cfg.assembly_id,
        aa=aa,
        role_map={name: tuple(chain_ids) for name, chain_ids in cfg.roles.items()},
        config=cfg,
        metadata=metadata,
    )
    ctx.rebuild_views()
    return ctx


def base_rows_for_context(ctx: Context) -> list[dict[str, Any]]:
    source_meta = dict(ctx.metadata.get("source", {}))
    structure_meta = dict(ctx.metadata.get("structure", {}))
    rows = empty_pdb_rows()
    rows.append(
        {
            "grain": "structure",
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "source__name": str(source_meta.get("name", "")),
            "source__format": str(source_meta.get("format", "")),
            "source__size_bytes": int(source_meta.get("size_bytes", 0) or 0),
            "source__mtime_ns": int(source_meta.get("mtime_ns", 0) or 0),
            "source__n_atoms_loaded": int(structure_meta.get("n_atoms_loaded", 0) or 0),
            "source__n_chains_loaded": int(structure_meta.get("n_chains_loaded", 0) or 0),
        }
    )

    for chain_id in sorted(ctx.chains):
        rows.append(
            {
                "grain": "chain",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "chain_id": chain_id,
            }
        )

    for role_name in sorted(ctx.roles):
        rows.append(
            {
                "grain": "role",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "role": role_name,
            }
        )

    for left_role, right_role in ctx.config.interface_pairs_for_outputs():
        rows.append(
            {
                "grain": "interface",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "pair": f"{left_role}__{right_role}",
                "role_left": left_role,
                "role_right": right_role,
            }
        )
    return rows


def run_unit(
    ctx: Context,
    unit: Any,
    pdb_rows: list[dict[str, Any]],
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
            pdb_rows.append(prefix_row(raw, unit.prefix, default_grain=getattr(unit, "grain", "structure")))
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


def superimposed_structures_dir(out_dir: Path) -> Path:
    return out_dir / SUPERIMPOSED_STRUCTURES_DIRNAME


def plugin_pdb_path(out_dir: Path, plugin_name: str) -> Path:
    return plugins_dir(out_dir) / f"{plugin_name}.pdb{TABLE_SUFFIX}"


def plugin_status_path(out_dir: Path, plugin_name: str) -> Path:
    return plugins_dir(out_dir) / f"{plugin_name}.plugin_status{TABLE_SUFFIX}"


def plugin_bad_path(out_dir: Path, plugin_name: str) -> Path:
    return plugins_dir(out_dir) / f"{plugin_name}.bad_files{TABLE_SUFFIX}"


def clear_final_outputs(out_dir: Path, *, cfg: Config | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing_metadata = read_output_metadata(out_dir)
    filenames = set(final_output_files(metadata=existing_metadata))
    filenames.update(final_output_files(cfg=cfg))
    filenames.update(OPTIONAL_DEBUG_OUTPUT_FILES)
    for filename in filenames:
        path = out_dir / filename
        if path.exists():
            path.unlink()
    analysis_dir = out_dir / "dataset_analysis"
    if analysis_dir.exists():
        shutil.rmtree(analysis_dir)
def _rewrite_embedded_output_paths(target_out_dir: Path, source_out_dir: Path) -> None:
    metadata = read_output_metadata(target_out_dir)
    pdb_path = pdb_output_path(target_out_dir, metadata=metadata)
    if pdb_path.exists():
        frame = read_pdb_table(pdb_path)
        for column in ("prepared__path", "rmsd__transformed_path"):
            if column not in frame.columns:
                continue
            updated: list[object] = []
            for value in frame[column].tolist():
                raw = str(value or "").strip()
                if not raw:
                    updated.append(value)
                    continue
                try:
                    resolved = Path(raw).resolve()
                    relative = resolved.relative_to(source_out_dir.resolve())
                    updated.append(str((target_out_dir.resolve() / relative).resolve()))
                except Exception:
                    updated.append(value)
            frame[column] = updated
        write_pdb_table(target_out_dir, frame, filename=pdb_path.name)

    manifest_path = prepared_manifest_path(target_out_dir)
    if manifest_path.exists():
        manifest = read_frame(manifest_path, MANIFEST_COLS)
        if "prepared_path" in manifest.columns:
            updated: list[str] = []
            for value in manifest["prepared_path"].astype(str).tolist():
                raw = str(value or "").strip()
                if not raw:
                    updated.append(raw)
                    continue
                try:
                    resolved = Path(raw).resolve()
                    relative = resolved.relative_to(source_out_dir.resolve())
                    updated.append(str((target_out_dir.resolve() / relative).resolve()))
                except Exception:
                    updated.append(raw)
            manifest["prepared_path"] = updated
        manifest.to_parquet(manifest_path, index=False)


def copy_final_outputs(source_out_dir: Path, target_out_dir: Path, *, cfg: Config | None = None) -> None:
    metadata = read_output_metadata(source_out_dir)
    filenames = final_output_files(cfg=cfg, metadata=metadata)
    clear_final_outputs(target_out_dir, cfg=cfg)
    target_prepared = prepared_dir(target_out_dir)
    if target_prepared.exists():
        shutil.rmtree(target_prepared)
    target_superimposed = superimposed_structures_dir(target_out_dir)
    if target_superimposed.exists():
        shutil.rmtree(target_superimposed)
    for filename in filenames:
        source_path = source_out_dir / filename
        if source_path.exists():
            shutil.copy2(source_path, target_out_dir / filename)
    for filename in OPTIONAL_DEBUG_OUTPUT_FILES:
        source_path = source_out_dir / filename
        if source_path.exists():
            shutil.copy2(source_path, target_out_dir / filename)
    if cfg is not None and cfg.keep_prepared_structures:
        source_prepared = prepared_dir(source_out_dir)
        if source_prepared.exists():
            shutil.copytree(source_prepared, target_prepared, dirs_exist_ok=True)
    source_superimposed = superimposed_structures_dir(source_out_dir)
    if source_superimposed.exists():
        shutil.copytree(source_superimposed, target_superimposed, dirs_exist_ok=True)
    _rewrite_embedded_output_paths(target_out_dir, source_out_dir)


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
