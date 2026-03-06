"""Pipeline orchestration over extracted table and workspace helpers."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from biotite.structure.io import save_structure

from .chunked import run_chunked_pipeline as _run_chunked_pipeline
from .config import Config
from .plugins import PLUGIN_REGISTRY
from .plugins.dataset_analysis.runtime import analyze_dataset_outputs
from .plugins.manipulation import MANIPULATION_REGISTRY
from .registry import instantiate_unit
from .tables import (
    BAD_COLS,
    MANIFEST_COLS,
    STATUS_COLS,
    TABLE_NAMES,
    TABLE_SUFFIX,
    empty_tables as _empty_tables,
    merge_table_frames as _merge_table_frames,
    read_frame as _read_frame,
    read_table as _read_table_parquet,
    rows_to_frame as _rows_to_frame,
    stack_table_frames as _stack_table_frames,
    write_frame as _write_frame,
    write_tables as _write_tables,
)
from .workspace import (
    base_rows_for_context as _base_rows_for_context,
    copy_final_outputs as _copy_final_outputs,
    discover_inputs as _discover,
    load_prepared_manifest as _load_prepared_manifest,
    plugin_dir as _plugin_dir,
    plugins_dir as _plugins_dir,
    prepare_context as _prepare_context,
    prepared_dir as _prepared_dir,
    prepared_filename as _prepared_filename,
    prepared_manifest_path as _prepared_manifest_path,
    prepared_structures_dir as _prepared_structures_dir,
    run_unit as _run_unit,
)


def _count_tables(tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    return {table_name: len(tables[table_name]) for table_name in TABLE_NAMES}


def _write_stage_outputs(
    out_dir: Path,
    tables: dict[str, pd.DataFrame],
    status_rows: list[dict[str, Any]],
    bad_rows: list[dict[str, Any]],
) -> dict[str, int]:
    _write_tables(out_dir, tables)
    _write_frame(out_dir / f"plugin_status{TABLE_SUFFIX}", status_rows, STATUS_COLS)
    _write_frame(out_dir / f"bad_files{TABLE_SUFFIX}", bad_rows, BAD_COLS)
    return {
        **_count_tables(tables),
        "status": len(status_rows),
        "bad": len(bad_rows),
    }


def _merge_tracking_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)


def _run_dataset_analyses(cfg: Config, out_dir: Path) -> None:
    if not cfg.dataset_analyses:
        return
    analyze_dataset_outputs(
        out_dir,
        dataset_analyses=tuple(cfg.dataset_analyses),
        dataset_analysis_params=cfg.dataset_analysis_params,
        dataset_annotations=cfg.dataset_annotations,
    )


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
    manipulation_units = [instantiate_unit(MANIPULATION_REGISTRY[name]) for name in cfg.manipulations]
    plugins_dir = _plugins_dir(out_dir)

    if prepared_dir.exists():
        shutil.rmtree(prepared_dir)
    if plugins_dir.exists():
        shutil.rmtree(plugins_dir)
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

    counts = _write_stage_outputs(prepared_dir, merged_tables, status_rows, bad_rows)
    _write_frame(_prepared_manifest_path(out_dir), manifest_rows, MANIFEST_COLS)
    return counts


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
    plugin = instantiate_unit(PLUGIN_REGISTRY[plugin_name])
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
    return _write_stage_outputs(plugin_dir, frames, status_rows, bad_rows)


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
    merged_status = _merge_tracking_frames(status_frames)
    merged_bad = _merge_tracking_frames(bad_frames)

    _write_tables(target_out_dir, merged_tables)
    merged_status.to_parquet(target_out_dir / f"plugin_status{TABLE_SUFFIX}", index=False)
    merged_bad.to_parquet(target_out_dir / f"bad_files{TABLE_SUFFIX}", index=False)

    return {
        **_count_tables(merged_tables),
        "status": len(merged_status),
        "bad": len(merged_bad),
    }


def run_chunked_pipeline(
    cfg: Config,
    *,
    chunk_size: int,
    workers: int = 1,
) -> dict[str, int]:
    return _run_chunked_pipeline(cfg, chunk_size=chunk_size, workers=workers)


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

    plugin_names = cfg.plugins
    for plugin_name in plugin_names:
        plugin_dir = _plugin_dir(out_dir, plugin_name)
        if not plugin_dir.exists():
            raise FileNotFoundError(f"Plugin outputs not found for configured plugin '{plugin_name}': {plugin_dir}")
        for table_name in TABLE_NAMES:
            plugin_frame = _read_table_parquet(plugin_dir / f"{table_name}{TABLE_SUFFIX}", table_name)
            merged_tables[table_name] = _merge_table_frames(merged_tables[table_name], plugin_frame, table_name)
        status_frames.append(_read_frame(plugin_dir / f"plugin_status{TABLE_SUFFIX}", STATUS_COLS))
        bad_frames.append(_read_frame(plugin_dir / f"bad_files{TABLE_SUFFIX}", BAD_COLS))

    merged_status = _merge_tracking_frames(status_frames)
    merged_bad = _merge_tracking_frames(bad_frames)

    _write_tables(out_dir, merged_tables)
    merged_status.to_parquet(out_dir / f"plugin_status{TABLE_SUFFIX}", index=False)
    merged_bad.to_parquet(out_dir / f"bad_files{TABLE_SUFFIX}", index=False)

    return {
        **_count_tables(merged_tables),
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
        _run_dataset_analyses(cfg, out_dir)
        return counts

    with tempfile.TemporaryDirectory(prefix="minimum_atw_run_") as tmp_dir:
        temp_cfg = cfg.model_copy(update={"out_dir": str(Path(tmp_dir).resolve())})
        prepare_outputs(temp_cfg)
        for plugin_name in temp_cfg.plugins:
            run_plugin(temp_cfg, plugin_name)
        counts = merge_outputs(temp_cfg)
        _copy_final_outputs(Path(temp_cfg.out_dir).resolve(), out_dir)
        _run_dataset_analyses(cfg, out_dir)
    return counts
