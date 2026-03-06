"""
Pipeline orchestration for minimum_atomworks.

This module implements the three-phase execution model:

1. prepare_outputs() - Load raw structures, apply manipulations, write base tables
   - Source: input_dir/*.pdb, *.cif
   - Output: _prepared/ with canonical tables and prepared structure files
   - Caching: Results are cached; can be reused by plugins

2. run_plugin() - Run a single plugin against prepared structures
   - Source: prepared structures from _prepared/
   - Output: _plugins/<plugin_name>/ with plugin-specific columns
   - Execution: One plugin per call, enables parallelization

3. merge_outputs() - Merge plugin outputs with base tables
   - Source: base tables + all plugin outputs
   - Output: Final tables in out_dir/ (structures.parquet, chains.parquet, etc.)
   - Schema: Plugins add prefixed columns (e.g., "iface__n_contacts")

Key concepts:
- TABLE_NAMES: Four normalized tables (structures, chains, roles, interfaces)
- IDENTITY_COLS: Columns that uniquely identify records (path, assembly_id, chain_id, etc.)
- KEY_COLS: Dict mapping table name to its identity column set
- prefix_row(): Adds plugin prefix to output columns while preserving identity keys
- Status tracking: Each phase writes plugin_status.parquet and bad_files.parquet

Status values:
- "ok": Plugin completed without errors
- "skipped_preflight": Plugin's available() method returned False
- "failed": Plugin raised an exception
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from biotite.structure.io import load_structure, save_structure

from .config import Config
from .plugins import PLUGIN_REGISTRY
from .plugins.base import Context
from .plugins.dataset_analysis.runtime import analyze_dataset_outputs
from .plugins.manipulation import MANIPULATION_REGISTRY


TABLE_NAMES = ("structures", "chains", "roles", "interfaces")
PREPARED_DIRNAME = "_prepared"
PREPARED_STRUCTURES_DIRNAME = "structures"
PREPARED_MANIFEST_NAME = "prepared_manifest.parquet"
PLUGINS_DIRNAME = "_plugins"
TABLE_SUFFIX = ".parquet"

IDENTITY_COLS = {
    "path",
    "assembly_id",
    "chain_id",
    "role",
    "pair",
    "role_left",
    "role_right",
}

KEY_COLS = {
    "structures": ["path", "assembly_id"],
    "chains": ["path", "assembly_id", "chain_id"],
    "roles": ["path", "assembly_id", "role"],
    "interfaces": ["path", "assembly_id", "pair", "role_left", "role_right"],
}

STATUS_COLS = ["path", "assembly_id", "plugin", "status", "message"]
BAD_COLS = ["path", "error"]
MANIFEST_COLS = ["path", "prepared_path"]
FINAL_OUTPUT_FILES = [f"{table_name}{TABLE_SUFFIX}" for table_name in TABLE_NAMES] + [
    f"plugin_status{TABLE_SUFFIX}",
    f"bad_files{TABLE_SUFFIX}",
]


class TableOps:
    """Common DataFrame operations for normalized tables.
    
    Consolidates scattered DataFrame utilities into a single, well-documented class.
    All operations ensure consistent sorting by identity columns.
    """
    
    @staticmethod
    def empty_frame(table_name: str) -> pd.DataFrame:
        """Create empty DataFrame with correct columns for table."""
        return pd.DataFrame(columns=KEY_COLS[table_name])
    
    @staticmethod
    def sort_frame(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
        """Sort DataFrame by identity columns (stable sort, preserves order)."""
        if df.empty:
            return df
        sort_cols = [col for col in KEY_COLS[table_name] if col in df.columns]
        if sort_cols:
            df = df.sort_values(sort_cols, kind="stable")
        return df.reset_index(drop=True)
    
    @staticmethod
    def from_rows(rows: list[dict[str, Any]], table_name: str) -> pd.DataFrame:
        """Create DataFrame from rows, sort by identity columns."""
        if not rows:
            return TableOps.empty_frame(table_name)
        df = pd.DataFrame(rows)
        # Order columns: identity keys first, then others
        ordered = [col for col in KEY_COLS[table_name] if col in df.columns]
        ordered.extend(col for col in df.columns if col not in ordered)
        return TableOps.sort_frame(df.loc[:, ordered], table_name)
    
    @staticmethod
    def read_frame(path: Path, columns: list[str]) -> pd.DataFrame:
        """Read DataFrame from parquet file."""
        if not path.exists():
            return pd.DataFrame(columns=columns)
        return pd.read_parquet(path)
    
    @staticmethod
    def read_table(path: Path, table_name: str) -> pd.DataFrame:
        """Read table DataFrame from parquet and sort by identity columns."""
        if not path.exists():
            return TableOps.empty_frame(table_name)
        return TableOps.sort_frame(pd.read_parquet(path), table_name)
    
    @staticmethod
    def merge_frames(base: pd.DataFrame, extra: pd.DataFrame, table_name: str) -> pd.DataFrame:
        """Merge extra DataFrame into base DataFrame on identity keys."""
        keys = KEY_COLS[table_name]
        if base.empty:
            base = TableOps.empty_frame(table_name)
        if extra.empty:
            return TableOps.sort_frame(base, table_name)

        # Validate merge keys exist
        missing = [col for col in keys if col not in extra.columns]
        if missing:
            raise ValueError(f"Missing merge keys for {table_name}: {', '.join(missing)}")

        # Reorder extra columns: keys first, then others
        extra = extra.loc[:, list(dict.fromkeys([*keys, *[col for col in extra.columns if col not in keys]]))]
        
        # Check for duplicates
        if extra.duplicated(keys).any():
            raise ValueError(f"Duplicate identity rows detected in {table_name}")
        if not base.empty and base.duplicated(keys).any():
            raise ValueError(f"Duplicate base identity rows detected in {table_name}")

        non_key_cols = [col for col in extra.columns if col not in keys]
        if not non_key_cols:
            return TableOps.sort_frame(base, table_name)

        # Check for column conflicts
        overlapping = [col for col in non_key_cols if col in base.columns]
        if overlapping:
            raise ValueError(f"Overlapping output columns detected in {table_name}: {', '.join(sorted(overlapping))}")

        if base.empty:
            return TableOps.sort_frame(extra.loc[:, [*keys, *non_key_cols]].copy(), table_name)

        # Perform merge
        merged = base.merge(extra.loc[:, [*keys, *non_key_cols]], on=keys, how="left", validate="one_to_one")
        return TableOps.sort_frame(merged, table_name)
    
    @staticmethod
    def write_tables(dir_path: Path, tables: dict[str, pd.DataFrame]) -> None:
        """Write multiple tables to parquet files in directory."""
        dir_path.mkdir(parents=True, exist_ok=True)
        for table_name in TABLE_NAMES:
            tables[table_name].to_parquet(dir_path / f"{table_name}{TABLE_SUFFIX}", index=False)
    
    @staticmethod
    def write_frame(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
        """Write rows to parquet file."""
        pd.DataFrame(rows, columns=columns).to_parquet(path, index=False)


def _prefix_row(row: dict[str, Any], prefix: str) -> dict[str, Any]:
    out = {}
    for key, value in row.items():
        if key == "__table__":
            continue
        if key in IDENTITY_COLS:
            out[key] = value
        else:
            out[f"{prefix}__{key}"] = value
    return out


def _empty_tables() -> dict[str, list[dict[str, Any]]]:
    return {table_name: [] for table_name in TABLE_NAMES}


def _empty_frame(table_name: str) -> pd.DataFrame:
    return TableOps.empty_frame(table_name)


def _sort_frame(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    return TableOps.sort_frame(df, table_name)


def _rows_to_frame(rows: list[dict[str, Any]], table_name: str) -> pd.DataFrame:
    return TableOps.from_rows(rows, table_name)


def _read_frame(path: Path, columns: list[str]) -> pd.DataFrame:
    return TableOps.read_frame(path, columns)


def _read_table_parquet(path: Path, table_name: str) -> pd.DataFrame:
    return TableOps.read_table(path, table_name)


def _merge_table_frames(base: pd.DataFrame, extra: pd.DataFrame, table_name: str) -> pd.DataFrame:
    return TableOps.merge_frames(base, extra, table_name)


def _stack_table_frames(frames: list[pd.DataFrame], table_name: str) -> pd.DataFrame:
    keys = KEY_COLS[table_name]
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return _empty_frame(table_name)

    combined = pd.concat(non_empty, ignore_index=True, sort=False)
    missing = [col for col in keys if col not in combined.columns]
    if missing:
        raise ValueError(f"Missing identity columns for {table_name}: {', '.join(missing)}")
    if combined.duplicated(keys).any():
        raise ValueError(f"Duplicate identity rows detected across datasets in {table_name}")
    return _sort_frame(combined, table_name)


def _write_tables(dir_path: Path, tables: dict[str, pd.DataFrame]) -> None:
    TableOps.write_tables(dir_path, tables)


def _write_frame(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    TableOps.write_frame(path, rows, columns)


def _discover(input_dir: Path) -> list[Path]:
    files = []
    for pattern in ("*.pdb", "*.cif"):
        files.extend(sorted(input_dir.glob(pattern)))
    return files


def _chunk_paths(paths: list[Path], chunk_size: int) -> list[list[Path]]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")
    return [paths[idx : idx + chunk_size] for idx in range(0, len(paths), chunk_size)]


def _chunk_dir_name(index: int) -> str:
    return f"chunk_{index:04d}"


def _prepare_chunk_input_dir(chunk_input_dir: Path, chunk_paths: list[Path]) -> None:
    chunk_input_dir.mkdir(parents=True, exist_ok=True)
    for source_path in chunk_paths:
        target_path = chunk_input_dir / source_path.name
        if target_path.exists():
            target_path.unlink()
        target_path.symlink_to(source_path.resolve())


def _run_chunk_job(
    *,
    config_data: dict[str, Any],
    chunk_paths: list[str],
    chunk_index: int,
    workspace_dir: str,
) -> dict[str, Any]:
    workspace_path = Path(workspace_dir).resolve()
    chunk_dir = workspace_path / _chunk_dir_name(chunk_index)
    chunk_input_dir = chunk_dir / "input"
    chunk_out_dir = chunk_dir / "out"
    _prepare_chunk_input_dir(chunk_input_dir, [Path(path).resolve() for path in chunk_paths])

    chunk_cfg = Config(**config_data).model_copy(
        update={
            "input_dir": str(chunk_input_dir),
            "out_dir": str(chunk_out_dir),
            "keep_intermediate_outputs": False,
            "dataset_analysis": False,
            "dataset_analyses": [],
        }
    )
    counts = run_pipeline(chunk_cfg)
    return {
        "chunk_index": chunk_index,
        "chunk_input_dir": str(chunk_input_dir),
        "chunk_out_dir": str(chunk_out_dir),
        "n_input_files": len(chunk_paths),
        "counts": counts,
    }


def _prepare_context(source_path: Path, structure_path: Path, cfg: Config) -> Context:
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


def _base_rows_for_context(ctx: Context) -> dict[str, list[dict[str, Any]]]:
    tables = _empty_tables()
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


def _run_unit(
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
            tables[table].append(_prefix_row(raw, unit.prefix))
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


def _prepared_dir(out_dir: Path) -> Path:
    return out_dir / PREPARED_DIRNAME


def _prepared_structures_dir(out_dir: Path) -> Path:
    return _prepared_dir(out_dir) / PREPARED_STRUCTURES_DIRNAME


def _prepared_manifest_path(out_dir: Path) -> Path:
    return _prepared_dir(out_dir) / PREPARED_MANIFEST_NAME


def _plugins_dir(out_dir: Path) -> Path:
    return out_dir / PLUGINS_DIRNAME


def _plugin_dir(out_dir: Path, plugin_name: str) -> Path:
    return _plugins_dir(out_dir) / plugin_name


def _cleanup_intermediate_outputs(out_dir: Path) -> None:
    prepared_dir = _prepared_dir(out_dir)
    plugins_dir = _plugins_dir(out_dir)
    if prepared_dir.exists():
        shutil.rmtree(prepared_dir)
    if plugins_dir.exists():
        shutil.rmtree(plugins_dir)


def _clear_final_outputs(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for filename in FINAL_OUTPUT_FILES:
        path = out_dir / filename
        if path.exists():
            path.unlink()
    analysis_dir = out_dir / "dataset_analysis"
    if analysis_dir.exists():
        shutil.rmtree(analysis_dir)


def _copy_final_outputs(source_out_dir: Path, target_out_dir: Path) -> None:
    _clear_final_outputs(target_out_dir)
    for filename in FINAL_OUTPUT_FILES:
        source_path = source_out_dir / filename
        if source_path.exists():
            shutil.copy2(source_path, target_out_dir / filename)


def _prepared_filename(source_path: Path) -> str:
    digest = hashlib.sha1(str(source_path.resolve()).encode("utf-8")).hexdigest()[:12]
    suffix = source_path.suffix.lower() if source_path.suffix.lower() in {".pdb", ".cif"} else ".pdb"
    return f"{source_path.stem}_{digest}{suffix}"


def _load_prepared_manifest(out_dir: Path) -> pd.DataFrame:
    manifest_path = _prepared_manifest_path(out_dir)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Prepared outputs not found: {_prepared_dir(out_dir)}")
    manifest = _read_frame(manifest_path, MANIFEST_COLS)
    if manifest.duplicated(["path"]).any():
        raise ValueError("Prepared manifest contains duplicate source paths")
    return manifest


def prepare_outputs(cfg: Config) -> dict[str, int]:
    """
    Prepare structures for analysis.
    
    Phase 1 of the pipeline. This phase is expensive but can be cached:
    
    1. Discovers raw structures in input_dir (*.pdb, *.cif)
    2. For each structure:
       - Loads atomic coordinates
       - Creates Context with role mappings
       - Applies manipulations (center, superimpose, etc.)
       - Writes prepared structure file for caching
       - Records in prepared_manifest.parquet
    3. Builds canonical base tables:
       - structures: one row per structure
       - chains: one row per chain  
       - roles: one row per semantic role
       - interfaces: one row per configured interface pair
    
    Args:
        cfg: Config with input_dir, out_dir, manipulations, roles, interface_pairs
        
    Returns:
        dict with row counts:
            {
                "structures": int,     # canonical structures rows
                "chains": int,         # canonical chains rows
                "roles": int,          # canonical roles rows
                "interfaces": int,     # canonical interfaces rows
                "status": int,         # manipulation status entries
                "bad": int,            # files that failed
            }
            
    Outputs:
        - _prepared/structures.parquet
        - _prepared/chains.parquet
        - _prepared/roles.parquet
        - _prepared/interfaces.parquet
        - _prepared/plugin_status.parquet (manipulation results)
        - _prepared/bad_files.parquet (load/manipulation failures)
        - _prepared/prepared_manifest.parquet (source → prepared path mapping)
        - _prepared/structures/ (prepared structure files for caching)
    """
    input_dir = Path(cfg.input_dir).resolve()
    out_dir = Path(cfg.out_dir).resolve()
    prepared_dir = _prepared_dir(out_dir)
    prepared_structures_dir = _prepared_structures_dir(out_dir)
    manipulation_units = [MANIPULATION_REGISTRY[name] for name in cfg.manipulations]

    if prepared_dir.exists():
        shutil.rmtree(prepared_dir)
    prepared_structures_dir.mkdir(parents=True, exist_ok=True)

    base_tables = _empty_tables()
    manipulation_tables_by_name = {unit.name: _empty_tables() for unit in manipulation_units}
    status_rows: list[dict[str, Any]] = []
    bad_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, str]] = []

    for source_path in _discover(input_dir):
        try:
            ctx = _prepare_context(source_path, source_path, cfg)
        except Exception as exc:
            bad_rows.append({"path": str(source_path.resolve()), "error": f"{type(exc).__name__}: {exc}"})
            continue

        manipulation_ok = True
        for unit in manipulation_units:
            manipulation_ok = _run_unit(ctx, unit, manipulation_tables_by_name[unit.name], status_rows) and manipulation_ok
        if not manipulation_ok:
            bad_rows.append({"path": ctx.path, "error": "prepare_failed"})
            continue

        base_rows = _base_rows_for_context(ctx)
        for table_name, rows in base_rows.items():
            base_tables[table_name].extend(rows)

        prepared_path = prepared_structures_dir / _prepared_filename(source_path)
        save_structure(prepared_path, ctx.aa)
        manifest_rows.append({"path": ctx.path, "prepared_path": str(prepared_path.resolve())})

    merged_tables = {
        table_name: _rows_to_frame(base_tables[table_name], table_name)
        for table_name in TABLE_NAMES
    }
    for unit in manipulation_units:
        unit_tables = manipulation_tables_by_name[unit.name]
        for table_name in TABLE_NAMES:
            merged_tables[table_name] = _merge_table_frames(
                merged_tables[table_name],
                _rows_to_frame(unit_tables[table_name], table_name),
                table_name,
            )

    _write_tables(prepared_dir, merged_tables)
    _write_frame(prepared_dir / f"plugin_status{TABLE_SUFFIX}", status_rows, STATUS_COLS)
    _write_frame(prepared_dir / f"bad_files{TABLE_SUFFIX}", bad_rows, BAD_COLS)
    _write_frame(_prepared_manifest_path(out_dir), manifest_rows, MANIFEST_COLS)

    return {
        "structures": len(merged_tables["structures"]),
        "chains": len(merged_tables["chains"]),
        "roles": len(merged_tables["roles"]),
        "interfaces": len(merged_tables["interfaces"]),
        "status": len(status_rows),
        "bad": len(bad_rows),
    }


def run_plugin(cfg: Config, plugin_name: str) -> dict[str, int]:
    """
    Run a single plugin against prepared structures.
    
    Phase 2a of the pipeline. Requires prepare_outputs to have been called first.
    
    1. Loads prepared structures from _prepared/
    2. Iterates through each prepared structure:
       - Creates Context from prepared structure
       - Runs plugin, collecting output rows
       - Records status (ok/skipped/failed)
    3. Writes plugin-specific tables:
       - _plugins/<plugin_name>/structures.parquet (if plugin emits to structures)
       - _plugins/<plugin_name>/chains.parquet (if plugin emits to chains)
       - _plugins/<plugin_name>/roles.parquet (if plugin emits to roles)
       - _plugins/<plugin_name>/interfaces.parquet (if plugin emits to interfaces)
    
    Can be called in parallel for different plugins to speed up processing.
    
    Args:
        cfg: Config with out_dir, superimpose/rosetta/interface settings
        plugin_name: Name of plugin to run (must exist in PLUGIN_REGISTRY)
        
    Returns:
        dict with row counts by table:
            {
                "structures": int,
                "chains": int,
                "roles": int,
                "interfaces": int,
                "status": int,  # plugin execution status entries
                "bad": int,     # structures that failed
            }
            
    Raises:
        KeyError: If plugin_name not found in PLUGIN_REGISTRY
        FileNotFoundError: If prepared outputs don't exist
        
    Outputs:
        - _plugins/<plugin_name>/{structures,chains,roles,interfaces}.parquet
        - _plugins/<plugin_name>/plugin_status.parquet
        - _plugins/<plugin_name>/bad_files.parquet
    """
    if plugin_name not in PLUGIN_REGISTRY:
        raise KeyError(f"Unknown plugin: {plugin_name}")

    out_dir = Path(cfg.out_dir).resolve()
    plugin_dir = _plugin_dir(out_dir, plugin_name)
    plugin = PLUGIN_REGISTRY[plugin_name]
    manifest = _load_prepared_manifest(out_dir)

    if plugin_dir.exists():
        shutil.rmtree(plugin_dir)

    plugin_tables = _empty_tables()
    status_rows: list[dict[str, Any]] = []
    bad_rows: list[dict[str, Any]] = []

    for row in manifest.itertuples(index=False):
        source_path = Path(row.path)
        prepared_path = Path(row.prepared_path)
        try:
            ctx = _prepare_context(source_path, prepared_path, cfg)
        except Exception as exc:
            bad_rows.append({"path": str(source_path.resolve()), "error": f"{type(exc).__name__}: {exc}"})
            continue
        _run_unit(ctx, plugin, plugin_tables, status_rows)

    frames = {table_name: _rows_to_frame(plugin_tables[table_name], table_name) for table_name in TABLE_NAMES}
    _write_tables(plugin_dir, frames)
    _write_frame(plugin_dir / f"plugin_status{TABLE_SUFFIX}", status_rows, STATUS_COLS)
    _write_frame(plugin_dir / f"bad_files{TABLE_SUFFIX}", bad_rows, BAD_COLS)

    return {
        "structures": len(frames["structures"]),
        "chains": len(frames["chains"]),
        "roles": len(frames["roles"]),
        "interfaces": len(frames["interfaces"]),
        "status": len(status_rows),
        "bad": len(bad_rows),
    }


def merge_dataset_outputs(source_out_dirs: list[str | Path], out_dir: str | Path) -> dict[str, int]:
    resolved_sources = [Path(path).resolve() for path in source_out_dirs]
    target_out_dir = Path(out_dir).resolve()
    if not resolved_sources:
        raise ValueError("At least one source out_dir is required")
    if target_out_dir in resolved_sources:
        raise ValueError("Target out_dir must be different from all source out_dirs")

    tables_by_name: dict[str, list[pd.DataFrame]] = {table_name: [] for table_name in TABLE_NAMES}
    status_frames: list[pd.DataFrame] = []
    bad_frames: list[pd.DataFrame] = []

    for source_dir in resolved_sources:
        if not source_dir.exists():
            raise FileNotFoundError(f"Source out_dir not found: {source_dir}")
        for table_name in TABLE_NAMES:
            tables_by_name[table_name].append(_read_table_parquet(source_dir / f"{table_name}{TABLE_SUFFIX}", table_name))
        status_frames.append(_read_frame(source_dir / f"plugin_status{TABLE_SUFFIX}", STATUS_COLS))
        bad_frames.append(_read_frame(source_dir / f"bad_files{TABLE_SUFFIX}", BAD_COLS))

    merged_tables = {
        table_name: _stack_table_frames(frames, table_name)
        for table_name, frames in tables_by_name.items()
    }
    merged_status = pd.concat(status_frames, ignore_index=True, sort=False).drop_duplicates().reset_index(drop=True)
    merged_bad = pd.concat(bad_frames, ignore_index=True, sort=False).drop_duplicates().reset_index(drop=True)

    _write_tables(target_out_dir, merged_tables)
    merged_status.to_parquet(target_out_dir / f"plugin_status{TABLE_SUFFIX}", index=False)
    merged_bad.to_parquet(target_out_dir / f"bad_files{TABLE_SUFFIX}", index=False)

    return {
        "structures": len(merged_tables["structures"]),
        "chains": len(merged_tables["chains"]),
        "roles": len(merged_tables["roles"]),
        "interfaces": len(merged_tables["interfaces"]),
        "status": len(merged_status),
        "bad": len(merged_bad),
    }


def run_chunked_pipeline(
    cfg: Config,
    *,
    chunk_size: int,
    workers: int = 1,
) -> dict[str, int]:
    input_paths = _discover(Path(cfg.input_dir).resolve())
    if not input_paths:
        raise FileNotFoundError(f"No .pdb or .cif files found in {Path(cfg.input_dir).resolve()}")

    chunks = _chunk_paths(input_paths, chunk_size)
    max_workers = max(1, int(workers))
    out_dir = Path(cfg.out_dir).resolve()
    _clear_final_outputs(out_dir)

    config_data = cfg.model_dump()
    with tempfile.TemporaryDirectory(prefix="minimum_atw_chunked_") as tmp_dir:
        workspace_dir = Path(tmp_dir).resolve()
        chunk_results: list[dict[str, Any]] = []

        jobs = [
            {
                "config_data": config_data,
                "chunk_paths": [str(path) for path in chunk_paths],
                "chunk_index": chunk_index,
                "workspace_dir": str(workspace_dir),
            }
            for chunk_index, chunk_paths in enumerate(chunks, start=1)
        ]

        def _submit_all(executor):
            futures = [executor.submit(_run_chunk_job, **job) for job in jobs]
            return [future.result() for future in concurrent.futures.as_completed(futures)]

        if max_workers == 1:
            chunk_results = [_run_chunk_job(**job) for job in jobs]
        else:
            try:
                with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                    chunk_results = _submit_all(executor)
            except PermissionError:
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    chunk_results = _submit_all(executor)

        chunk_results = sorted(chunk_results, key=lambda item: int(item["chunk_index"]))
        merged_counts = merge_dataset_outputs(
            [item["chunk_out_dir"] for item in chunk_results],
            out_dir,
        )
        if cfg.dataset_analyses:
            analyze_dataset_outputs(
                out_dir,
                dataset_analyses=tuple(cfg.dataset_analyses),
                dataset_annotations=cfg.dataset_annotations,
            )

    merged_counts["chunks"] = len(chunks)
    merged_counts["chunk_size"] = chunk_size
    merged_counts["workers"] = max_workers
    return merged_counts


def merge_outputs(cfg: Config) -> dict[str, int]:
    """
    Merge plugin outputs with base tables.
    
    Phase 2b of the pipeline. Requires prepare_outputs and run_plugin calls first.
    
    1. Reads canonical base tables from _prepared/
    2. For each plugin in _plugins/:
       - Reads plugin's output tables
       - Merges with base tables on identity keys (left join)
       - Validates no duplicate columns
    3. Consolidates status/error tracking from all phases
    4. Writes final merged tables to out_dir/
    
    Merge strategy:
    - Left join: preserves all base rows
    - Key match: identity columns (path, assembly_id, chain_id, etc.)
    - Column prefix: plugin columns are already prefixed (e.g., "iface__n_contacts")
    - Validation: rejects duplicate non-prefixed columns
    
    Args:
        cfg: Config with out_dir
        
    Returns:
        dict with final row counts:
            {
                "structures": int,     # final structures table
                "chains": int,         # final chains table
                "roles": int,          # final roles table
                "interfaces": int,     # final interfaces table
                "status": int,         # all status entries (consolidated)
                "bad": int,            # all error entries (consolidated)
            }
            
    Raises:
        FileNotFoundError: If prepared outputs don't exist
        ValueError: If columns conflict or identity keys are missing
        
    Outputs:
        - out_dir/structures.parquet
        - out_dir/chains.parquet
        - out_dir/roles.parquet
        - out_dir/interfaces.parquet
        - out_dir/plugin_status.parquet (from all phases)
        - out_dir/bad_files.parquet (from all phases)
    """
    out_dir = Path(cfg.out_dir).resolve()
    prepared_dir = _prepared_dir(out_dir)
    if not prepared_dir.exists():
        raise FileNotFoundError(f"Prepared outputs not found: {prepared_dir}")

    merged_tables = {
        table_name: _read_table_parquet(prepared_dir / f"{table_name}{TABLE_SUFFIX}", table_name)
        for table_name in TABLE_NAMES
    }
    status_frames = [_read_frame(prepared_dir / f"plugin_status{TABLE_SUFFIX}", STATUS_COLS)]
    bad_frames = [_read_frame(prepared_dir / f"bad_files{TABLE_SUFFIX}", BAD_COLS)]

    plugins_dir = _plugins_dir(out_dir)
    plugin_names = sorted(path.name for path in plugins_dir.iterdir() if path.is_dir()) if plugins_dir.exists() else []
    for plugin_name in plugin_names:
        plugin_dir = plugins_dir / plugin_name
        for table_name in TABLE_NAMES:
            plugin_frame = _read_table_parquet(plugin_dir / f"{table_name}{TABLE_SUFFIX}", table_name)
            merged_tables[table_name] = _merge_table_frames(merged_tables[table_name], plugin_frame, table_name)
        status_frames.append(_read_frame(plugin_dir / f"plugin_status{TABLE_SUFFIX}", STATUS_COLS))
        bad_frames.append(_read_frame(plugin_dir / f"bad_files{TABLE_SUFFIX}", BAD_COLS))

    merged_status = pd.concat(status_frames, ignore_index=True).drop_duplicates().reset_index(drop=True)
    merged_bad = pd.concat(bad_frames, ignore_index=True).drop_duplicates().reset_index(drop=True)

    _write_tables(out_dir, merged_tables)
    merged_status.to_parquet(out_dir / f"plugin_status{TABLE_SUFFIX}", index=False)
    merged_bad.to_parquet(out_dir / f"bad_files{TABLE_SUFFIX}", index=False)

    return {
        "structures": len(merged_tables["structures"]),
        "chains": len(merged_tables["chains"]),
        "roles": len(merged_tables["roles"]),
        "interfaces": len(merged_tables["interfaces"]),
        "status": len(merged_status),
        "bad": len(merged_bad),
    }


def run_pipeline(cfg: Config) -> dict[str, int]:
    """
    Execute the complete pipeline end-to-end.
    
    Convenience function that orchestrates all phases:
    1. prepare_outputs() → cached base tables
    2. run_plugin() for each plugin in cfg.plugins
    3. merge_outputs() → final output tables
    4. analyze_dataset_outputs() if cfg.dataset_analyses is configured
    5. Cleanup intermediate files if cfg.keep_intermediate_outputs=False
    
    This is the default execution path when users run:
        python -m minimum_atw.cli run --config config.yaml
    
    For more control, use staged execution:
        minimize_atw.cli prepare ...
        minimum_atw.cli run-plugin ... (multiple times)
        minimum_atw.cli merge ...
        minimum_atw.cli analyze-dataset ...
    
    Args:
        cfg: Config with all pipeline settings
        
    Returns:
        dict with final row counts (see merge_outputs)
        
    Outputs:
        Final tables in cfg.out_dir:
        - structures.parquet, chains.parquet, roles.parquet, interfaces.parquet
        - plugin_status.parquet, bad_files.parquet
        - dataset_analysis/* (if dataset_analyses configured)
        
        Intermediate files are deleted unless keep_intermediate_outputs=True
    """
    out_dir = Path(cfg.out_dir).resolve()
    if cfg.keep_intermediate_outputs:
        prepare_outputs(cfg)
        for plugin_name in cfg.plugins:
            run_plugin(cfg, plugin_name)
        counts = merge_outputs(cfg)
        if cfg.dataset_analyses:
            analyze_dataset_outputs(
                out_dir,
                dataset_analyses=tuple(cfg.dataset_analyses),
                dataset_annotations=cfg.dataset_annotations,
            )
        return counts

    with tempfile.TemporaryDirectory(prefix="minimum_atw_run_") as tmp_dir:
        temp_cfg = cfg.model_copy(update={"out_dir": str(Path(tmp_dir).resolve())})
        prepare_outputs(temp_cfg)
        for plugin_name in temp_cfg.plugins:
            run_plugin(temp_cfg, plugin_name)
        counts = merge_outputs(temp_cfg)
        _copy_final_outputs(Path(temp_cfg.out_dir).resolve(), out_dir)
        if cfg.dataset_analyses:
            analyze_dataset_outputs(
                out_dir,
                dataset_analyses=tuple(cfg.dataset_analyses),
                dataset_annotations=cfg.dataset_annotations,
            )
    return counts
