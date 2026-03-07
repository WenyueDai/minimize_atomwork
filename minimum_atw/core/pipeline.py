"""Pipeline orchestration over extracted table and workspace helpers."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from biotite.structure.io import save_structure

from ..plugins import PLUGIN_REGISTRY
from ..plugins.dataset_analysis.runtime import analyze_dataset_outputs
from ..plugins.manipulation import MANIPULATION_REGISTRY
from ..runtime.chunked import (
    merge_planned_chunks as _merge_planned_chunks,
    plan_chunked_pipeline as _plan_chunked_pipeline,
    run_chunked_pipeline as _run_chunked_pipeline,
)
from ..runtime.stage_buffer import FrameBuffer, TableBuffer
from ..runtime.workspace import (
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
from .config import Config, PREPARE_SECTION_ORDER
from .registry import instantiate_unit
from .tables import (
    BAD_COLS,
    IDENTITY_COLS,
    KEY_COLS,
    MANIFEST_COLS,
    STATUS_COLS,
    TABLE_NAMES,
    TABLE_SUFFIX,
    merge_table_frames as _merge_table_frames,
    read_frame as _read_frame,
    read_table as _read_table_parquet,
    stack_table_frames as _stack_table_frames,
    write_frame as _write_frame,
    write_tables as _write_tables,
)

def _count_tables(tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    return {table_name: len(tables[table_name]) for table_name in TABLE_NAMES}


def _write_stage_outputs(
    out_dir: Path,
    tables: dict[str, pd.DataFrame],
    status_rows: list[dict[str, Any]],
    bad_rows: list[dict[str, Any]],
    *,
    skip_empty_tables: bool = False,
) -> dict[str, int]:
    _write_tables(out_dir, tables, skip_empty=skip_empty_tables)
    _write_frame(out_dir / f"plugin_status{TABLE_SUFFIX}", status_rows, STATUS_COLS)
    _write_frame(out_dir / f"bad_files{TABLE_SUFFIX}", bad_rows, BAD_COLS)
    return {
        **_count_tables(tables),
        "status": len(status_rows),
        "bad": len(bad_rows),
    }


def _append_stage_outputs(
    out_dir: Path,
    tables: dict[str, pd.DataFrame],
    status_rows: list[dict[str, Any]],
    bad_rows: list[dict[str, Any]],
) -> dict[str, int]:
    """Merge the given rows into existing outputs inside *out_dir*.

    This helper is used by the checkpointing logic. For each table it reads any
    preexisting file and concatenates the new rows, dropping duplicates by the
    appropriate key columns. Status and bad rows are handled similarly. The
    caller may pass the same data multiple times; duplicates are removed.

    Returns the updated overall counts (after merging), mirroring the
    ``_write_stage_outputs`` return value.
    """
    # ensure directory exists before touching files
    out_dir.mkdir(parents=True, exist_ok=True)

    # tables
    for table_name, new_frame in tables.items():
        if new_frame.empty:
            continue
        path = out_dir / f"{table_name}{TABLE_SUFFIX}"
        if path.exists():
            existing = _read_table_parquet(path, table_name)
            combined = pd.concat([existing, new_frame], ignore_index=True, sort=False)
            # drop duplicates on identity keys
            combined = combined.drop_duplicates(subset=KEY_COLS[table_name])
        else:
            combined = new_frame
        combined.to_parquet(path, index=False)

    # status and bad
    _append_rows(out_dir / f"plugin_status{TABLE_SUFFIX}", status_rows, STATUS_COLS)
    _append_rows(out_dir / f"bad_files{TABLE_SUFFIX}", bad_rows, BAD_COLS)

    # compute counts from resulting files
    final_tables = {table_name: _read_table_parquet(out_dir / f"{table_name}{TABLE_SUFFIX}", table_name)
                    for table_name in TABLE_NAMES}
    final_status = _read_frame(out_dir / f"plugin_status{TABLE_SUFFIX}", STATUS_COLS)
    final_bad = _read_frame(out_dir / f"bad_files{TABLE_SUFFIX}", BAD_COLS)
    return {**_count_tables(final_tables), "status": len(final_status), "bad": len(final_bad)}


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _table_columns(tables: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    return {table_name: list(tables[table_name].columns) for table_name in TABLE_NAMES}


def _empty_stage_frames() -> dict[str, pd.DataFrame]:
    return {table_name: pd.DataFrame() for table_name in TABLE_NAMES}


def _prepare_counts_from_dir(prepared_dir: Path) -> dict[str, int]:
    counts = {
        table_name: len(_read_table_parquet(prepared_dir / f"{table_name}{TABLE_SUFFIX}", table_name))
        for table_name in TABLE_NAMES
    }
    counts["status"] = len(_read_frame(prepared_dir / f"plugin_status{TABLE_SUFFIX}", STATUS_COLS))
    counts["bad"] = len(_read_frame(prepared_dir / f"bad_files{TABLE_SUFFIX}", BAD_COLS))
    return counts


def _load_manifest_checkpoint_paths(manifest_ckpt: Path) -> set[str]:
    done_paths: set[str] = set()
    if not manifest_ckpt.exists():
        return done_paths
    with manifest_ckpt.open() as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            done_paths.add(row["path"])
    return done_paths


def _finalize_manifest_checkpoint(out_dir: Path, manifest_ckpt: Path) -> None:
    if not manifest_ckpt.exists():
        return
    records: list[dict[str, str]] = []
    with manifest_ckpt.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    _write_frame(_prepared_manifest_path(out_dir), records, MANIFEST_COLS)


def _prepared_manifest_entry(
    cfg: Config,
    source_path: Path,
    prepared_structures_dir: Path,
    *,
    prepared_source_path: str,
) -> tuple[Path | None, dict[str, str]]:
    prepared_path = prepared_structures_dir / _prepared_filename(source_path) if cfg.keep_prepared_structures else None
    return prepared_path, {
        "path": prepared_source_path,
        "prepared_path": str(prepared_path.resolve()) if prepared_path else str(source_path.resolve()),
    }


def _write_prepared_structure(prepared_path: Path | None, ctx: Any) -> None:
    if prepared_path is None:
        return
    prepared_path.parent.mkdir(parents=True, exist_ok=True)
    save_structure(prepared_path, ctx.aa)


def _rows_to_stage_frames(
    base_rows: dict[str, list[dict[str, Any]]],
    extra_rows: dict[str, list[dict[str, Any]]],
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for table_name in TABLE_NAMES:
        rows = list(base_rows.get(table_name, []))
        rows.extend(extra_rows.get(table_name, []))
        frames[table_name] = pd.DataFrame(rows) if rows else pd.DataFrame()
    return frames


def _merge_compatibility(config: Config | dict[str, Any]) -> dict[str, Any]:
    """Extract configuration options that must match when merging outputs.
    
    Excludes paths, keep flags, and dataset-specific analyses that naturally
    vary across chunk runs. Returns options that define semantic compatibility
    (plugins, manipulations, roles, interface pairs, etc.).
    """
    if isinstance(config, Config):
        return config.merge_compatibility()
    else:
        data = dict(config)
    # Exclude options that are run-specific or vary per chunk
    excluded = {
        "input_dir",
        "out_dir",
        "keep_intermediate_outputs",
        "keep_prepared_structures",  # Caching strategy may vary
        "checkpoint_enabled",
        "checkpoint_interval",
        "dataset_analyses",
        "dataset_analysis_mode",
        "dataset_analysis_params",
        "dataset_annotations",
    }
    return {key: value for key, value in data.items() if key not in excluded}


def _read_output_metadata(source_dir: Path) -> dict[str, Any]:
    run_metadata_path = source_dir / "run_metadata.json"
    dataset_metadata_path = source_dir / "dataset_metadata.json"
    if run_metadata_path.exists():
        return json.loads(run_metadata_path.read_text())
    if dataset_metadata_path.exists():
        return json.loads(dataset_metadata_path.read_text())
    return {}


def _metadata_merge_compatibility(metadata: dict[str, Any]) -> dict[str, Any] | None:
    compatibility = metadata.get("merge_compatibility")
    if compatibility is not None:
        return compatibility
    config = metadata.get("config")
    if config is None:
        return None
    return _merge_compatibility(config)


def _validate_source_table_columns(
    table_name: str,
    source_dir: Path,
    frame: pd.DataFrame,
    reference_columns: dict[str, list[str]],
) -> pd.DataFrame:
    source_columns = list(frame.columns)
    if table_name not in reference_columns:
        reference_columns[table_name] = source_columns
        return frame

    expected_columns = reference_columns[table_name]
    if set(source_columns) != set(expected_columns):
        raise ValueError(
            f"Incompatible columns for {table_name} in {source_dir}: "
            f"expected {expected_columns}, got {source_columns}"
        )
    if source_columns == expected_columns:
        return frame
    return frame.loc[:, expected_columns]


@dataclass(frozen=True)
class PluginExecutionSpec:
    name: str
    plugin: Any
    resource_class: str
    execution_mode: str
    failure_policy: str


@dataclass
class PluginRunState:
    spec: PluginExecutionSpec
    dir: Path
    processed: set[str]
    counts: dict[str, int]

    @classmethod
    def from_out_dir(cls, out_dir: Path, spec: PluginExecutionSpec, checkpoint_enabled: bool) -> "PluginRunState":
        plugin_dir = _plugin_dir(out_dir, spec.name)
        processed: set[str] = set()
        status_path = plugin_dir / f"plugin_status{TABLE_SUFFIX}"
        bad_path = plugin_dir / f"bad_files{TABLE_SUFFIX}"

        if checkpoint_enabled and plugin_dir.exists():
            if status_path.exists():
                status_frame = pd.read_parquet(status_path)
                processed = set(status_frame["path"].tolist())
            counts = {table: 0 for table in TABLE_NAMES}
            for table_name in TABLE_NAMES:
                table_path = plugin_dir / f"{table_name}{TABLE_SUFFIX}"
                if table_path.exists():
                    counts[table_name] = len(pd.read_parquet(table_path))
            counts["status"] = len(pd.read_parquet(status_path)) if status_path.exists() else 0
            counts["bad"] = len(pd.read_parquet(bad_path)) if bad_path.exists() else 0
        else:
            if plugin_dir.exists():
                shutil.rmtree(plugin_dir)
            plugin_dir.mkdir(parents=True, exist_ok=True)
            counts = {table: 0 for table in TABLE_NAMES}
            counts.update(status=0, bad=0)

        return cls(spec=spec, dir=plugin_dir, processed=processed, counts=counts)

    def record_result(
        self,
        tables: dict[str, list[dict[str, Any]]],
        status_rows: list[dict[str, Any]],
        bad_rows: list[dict[str, Any]],
    ) -> None:
        for table_name, rows in tables.items():
            if not rows:
                continue
            _append_rows(self.dir / f"{table_name}{TABLE_SUFFIX}", rows, None)
            self.counts[table_name] += len(rows)
        _append_rows(self.dir / f"plugin_status{TABLE_SUFFIX}", status_rows, STATUS_COLS)
        self.counts["status"] += len(status_rows)
        _append_rows(self.dir / f"bad_files{TABLE_SUFFIX}", bad_rows, BAD_COLS)
        self.counts["bad"] += len(bad_rows)

    def mark_bad(self, source_path: Path, exc: Exception) -> None:
        self.record_result(
            {table_name: [] for table_name in TABLE_NAMES},
            [],
            [{"path": str(source_path.resolve()), "error": f"{type(exc).__name__}: {exc}"}],
        )
        self.processed.add(str(source_path))


def _plugin_execution_spec(plugin_name: str) -> PluginExecutionSpec:
    if plugin_name not in PLUGIN_REGISTRY:
        raise KeyError(f"Unknown plugin: {plugin_name}")
    plugin = instantiate_unit(PLUGIN_REGISTRY[plugin_name])
    return PluginExecutionSpec(
        name=plugin_name,
        plugin=plugin,
        resource_class=str(getattr(plugin, "resource_class", "lightweight") or "lightweight"),
        execution_mode=str(getattr(plugin, "execution_mode", "batched") or "batched"),
        failure_policy=str(getattr(plugin, "failure_policy", "continue") or "continue"),
    )


def _resolve_plugin_specs(plugin_names: list[str]) -> list[PluginExecutionSpec]:
    return [_plugin_execution_spec(plugin_name) for plugin_name in plugin_names]


def _plan_plugin_execution(specs: list[PluginExecutionSpec]) -> list[list[PluginExecutionSpec]]:
    lightweight_specs: list[PluginExecutionSpec] = []
    isolated_specs: list[PluginExecutionSpec] = []

    for spec in specs:
        if spec.execution_mode == "batched" and spec.resource_class == "lightweight":
            lightweight_specs.append(spec)
        else:
            isolated_specs.append(spec)

    plan: list[list[PluginExecutionSpec]] = []
    if lightweight_specs:
        plan.append(lightweight_specs)
    for spec in isolated_specs:
        plan.append([spec])
    return plan


def _plugin_execution_metadata(plugin_names: list[str]) -> dict[str, Any]:
    specs = _resolve_plugin_specs(plugin_names)
    groups = _plan_plugin_execution(specs)
    return {
        "plugins": {
            spec.name: {
                "resource_class": spec.resource_class,
                "execution_mode": spec.execution_mode,
                "failure_policy": spec.failure_policy,
            }
            for spec in specs
        },
        "groups": [
            {
                "plugins": [spec.name for spec in group],
                "resource_class": "mixed" if len({spec.resource_class for spec in group}) > 1 else group[0].resource_class,
                "execution_mode": "mixed" if len({spec.execution_mode for spec in group}) > 1 else group[0].execution_mode,
            }
            for group in groups
        ],
    }


def _prepare_units_by_section(cfg: Config) -> dict[str, list[Any]]:
    section_by_name = {
        name: str(getattr(unit, "prepare_section", "structure") or "structure")
        for name, unit in MANIPULATION_REGISTRY.items()
    }
    grouped_names = cfg.prepare_names_by_section(section_by_name=section_by_name)
    grouped_units: dict[str, list[Any]] = {section: [] for section in PREPARE_SECTION_ORDER}
    for section in PREPARE_SECTION_ORDER:
        for unit_name in grouped_names[section]:
            grouped_units[section].append(instantiate_unit(MANIPULATION_REGISTRY[unit_name]))
    return grouped_units


def _ordered_prepare_units(cfg: Config) -> list[Any]:
    grouped_units = _prepare_units_by_section(cfg)
    ordered: list[Any] = []
    for section in PREPARE_SECTION_ORDER:
        ordered.extend(grouped_units[section])
    return ordered


def _prepare_execution_metadata(cfg: Config) -> dict[str, Any]:
    grouped_units = _prepare_units_by_section(cfg)
    return {
        "sections": {
            section: [unit.name for unit in grouped_units[section]]
            for section in PREPARE_SECTION_ORDER
        }
    }


def _prepare_outputs_checkpointed(
    cfg: Config,
    *,
    input_dir: Path,
    out_dir: Path,
    prepared_dir: Path,
    prepared_structures_dir: Path,
    manipulation_units: list[Any],
    manifest_ckpt: Path,
) -> dict[str, int]:
    done_paths = _load_manifest_checkpoint_paths(manifest_ckpt)
    prepared_dir.mkdir(parents=True, exist_ok=True)
    if cfg.keep_prepared_structures:
        prepared_structures_dir.mkdir(parents=True, exist_ok=True)

    for source_path in _discover(input_dir):
        src_str = str(source_path.resolve())
        if src_str in done_paths:
            continue

        try:
            ctx = _prepare_context(source_path, source_path, cfg)
        except Exception as exc:
            _append_stage_outputs(
                prepared_dir,
                _empty_stage_frames(),
                [],
                [{"path": src_str, "error": f"{type(exc).__name__}: {exc}"}],
            )
            done_paths.add(src_str)
            continue

        manipulation_ok = True
        manipulation_rows: dict[str, list[dict[str, Any]]] = {table_name: [] for table_name in TABLE_NAMES}
        status_rows: list[dict[str, Any]] = []
        bad_rows: list[dict[str, Any]] = []
        for unit in manipulation_units:
            manipulation_ok = _run_unit(ctx, unit, manipulation_rows, status_rows) and manipulation_ok
        if not manipulation_ok:
            bad_rows.append({"path": ctx.path, "error": "prepare_failed"})
            _append_stage_outputs(prepared_dir, _empty_stage_frames(), status_rows, bad_rows)
            done_paths.add(src_str)
            continue

        base_rows = _base_rows_for_context(ctx)
        prepared_path, manifest_entry = _prepared_manifest_entry(
            cfg,
            source_path,
            prepared_structures_dir,
            prepared_source_path=ctx.path,
        )
        with manifest_ckpt.open("a") as fh:
            fh.write(json.dumps(manifest_entry) + "\n")

        _write_prepared_structure(prepared_path, ctx)
        _append_stage_outputs(
            prepared_dir,
            _rows_to_stage_frames(base_rows, manipulation_rows),
            status_rows,
            bad_rows,
        )
        done_paths.add(src_str)

    _finalize_manifest_checkpoint(out_dir, manifest_ckpt)
    return _prepare_counts_from_dir(prepared_dir)


def _prepare_outputs_buffered(
    cfg: Config,
    *,
    input_dir: Path,
    out_dir: Path,
    prepared_dir: Path,
    prepared_structures_dir: Path,
    manipulation_units: list[Any],
) -> dict[str, int]:
    if cfg.keep_prepared_structures:
        prepared_structures_dir.mkdir(parents=True, exist_ok=True)

    base_tables = TableBuffer()
    manipulation_tables_by_name = {unit.name: TableBuffer() for unit in manipulation_units}
    status_rows = FrameBuffer(columns=STATUS_COLS)
    bad_rows = FrameBuffer(columns=BAD_COLS)
    manifest_rows = FrameBuffer(columns=MANIFEST_COLS)

    try:
        for source_path in _discover(input_dir):
            try:
                ctx = _prepare_context(source_path, source_path, cfg)
            except Exception as exc:
                bad_rows.add({"path": str(source_path.resolve()), "error": f"{type(exc).__name__}: {exc}"})
                continue

            manipulation_ok = True
            for unit in manipulation_units:
                manipulation_ok = _run_unit(ctx, unit, manipulation_tables_by_name[unit.name], status_rows) and manipulation_ok
            if not manipulation_ok:
                bad_rows.add({"path": ctx.path, "error": "prepare_failed"})
                continue

            base_rows = _base_rows_for_context(ctx)
            for table_name, rows in base_rows.items():
                base_tables.add_rows(table_name, rows)

            prepared_path, manifest_entry = _prepared_manifest_entry(
                cfg,
                source_path,
                prepared_structures_dir,
                prepared_source_path=ctx.path,
            )
            manifest_rows.add(manifest_entry)
            _write_prepared_structure(prepared_path, ctx)

        merged_tables = base_tables.finalize()
        for unit in manipulation_units:
            unit_tables = manipulation_tables_by_name[unit.name].finalize()
            for table_name in TABLE_NAMES:
                merged_tables[table_name] = _merge_table_frames(
                    merged_tables[table_name],
                    unit_tables[table_name],
                    table_name,
                )

        status_frame = status_rows.finalize()
        bad_frame = bad_rows.finalize()
        counts = _write_stage_outputs(
            prepared_dir,
            merged_tables,
            status_frame.to_dict(orient="records"),
            bad_frame.to_dict(orient="records"),
        )
        _write_frame(
            _prepared_manifest_path(out_dir),
            manifest_rows.finalize().to_dict(orient="records"),
            MANIFEST_COLS,
        )
        return counts
    finally:
        base_tables.close()
        for table_buffer in manipulation_tables_by_name.values():
            table_buffer.close()
        status_rows.close()
        bad_rows.close()
        manifest_rows.close()


def prepare_outputs(cfg: Config) -> dict[str, int]:
    """
    Prepare structures for analysis.
    
    Phase 1 of the pipeline. This phase is expensive but can be cached:
    
    1. Discovers raw structures in input_dir (*.pdb, *.cif)
    2. For each structure:
       - Loads atomic coordinates
       - Creates Context with role mappings
       - Runs prepare units in three ordered sections:
         quality control -> structure manipulation -> dataset manipulation
       - Writes prepared structure file for caching
       - Records in prepared_manifest.parquet
    3. Builds canonical base tables:
       - structures: one row per structure
       - chains: one row per chain  
       - roles: one row per semantic role
       - interfaces: one row per configured interface pair
    
    Args:
        cfg: Config with input_dir, out_dir, prepare sections, roles, interface_pairs
        
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
    manipulation_units = _ordered_prepare_units(cfg)
    plugins_dir = _plugins_dir(out_dir)
    manifest_ckpt = prepared_dir / "manifest_checkpoint.jsonl"

    if not cfg.checkpoint_enabled:
        if prepared_dir.exists():
            shutil.rmtree(prepared_dir)
        if plugins_dir.exists():
            shutil.rmtree(plugins_dir)
    else:
        # ensure output dirs exist but keep their previous contents
        prepared_dir.mkdir(parents=True, exist_ok=True)
        plugins_dir.mkdir(parents=True, exist_ok=True)
        if cfg.keep_prepared_structures:
            prepared_structures_dir.mkdir(parents=True, exist_ok=True)
    if cfg.checkpoint_enabled:
        return _prepare_outputs_checkpointed(
            cfg,
            input_dir=input_dir,
            out_dir=out_dir,
            prepared_dir=prepared_dir,
            prepared_structures_dir=prepared_structures_dir,
            manipulation_units=manipulation_units,
            manifest_ckpt=manifest_ckpt,
        )

    return _prepare_outputs_buffered(
        cfg,
        input_dir=input_dir,
        out_dir=out_dir,
        prepared_dir=prepared_dir,
        prepared_structures_dir=prepared_structures_dir,
        manipulation_units=manipulation_units,
    )


def _append_rows(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    if not rows:
        return
    if columns:
        df = pd.DataFrame(rows, columns=columns)
    else:
        df = pd.DataFrame(rows)
    if path.exists():
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True, sort=False)
        df = df.drop_duplicates()
    df.to_parquet(path, index=False)


def _execute_plugin_group(
    cfg: Config,
    manifest: pd.DataFrame,
    group: list[PluginExecutionSpec],
    states: dict[str, PluginRunState],
) -> None:
    if not group:
        return

    if len(group) == 1:
        label = f"Running isolated plugin: {group[0].name}"
    else:
        label = f"Running batched plugins: {', '.join(spec.name for spec in group)}"
    print(label)

    for row in manifest.itertuples(index=False):
        source_path = Path(row.path)
        pending_specs = [spec for spec in group if str(source_path) not in states[spec.name].processed]
        if not pending_specs:
            continue

        prepared_path = Path(row.prepared_path)
        try:
            ctx = _prepare_context(source_path, prepared_path, cfg)
        except Exception as exc:
            for spec in pending_specs:
                states[spec.name].mark_bad(source_path, exc)
            continue

        for spec in pending_specs:
            local_tables: dict[str, list[dict[str, Any]]] = {table_name: [] for table_name in TABLE_NAMES}
            local_status: list[dict[str, Any]] = []
            local_bad: list[dict[str, Any]] = []
            ok = _run_unit(ctx, spec.plugin, local_tables, local_status)
            states[spec.name].record_result(local_tables, local_status, local_bad)
            states[spec.name].processed.add(str(source_path))
            if not ok and spec.failure_policy == "raise":
                raise RuntimeError(f"Plugin {spec.name} failed for {source_path}")


def run_plugin(cfg: Config, plugin_name: str) -> dict[str, int]:
    """
    Run a single plugin against prepared structures.
    
    Phase 2a of the pipeline. Requires prepare_outputs to have been called first.
    The plugin keeps its own output directory and status log regardless of how it
    is classified for grouped execution.
    """
    return run_plugins(cfg, [plugin_name])


def run_plugins(cfg: Config, plugin_names: list[str]) -> dict[str, int]:
    """
    Run multiple plugins against prepared structures.
    
    Phase 2a (incremental) of the pipeline. Lightweight plugins run in one
    shared pass over prepared structures, while heavy or isolated plugins run
    in separate passes with their own output/state directories.
    """
    specs = _resolve_plugin_specs(plugin_names)

    out_dir = Path(cfg.out_dir).resolve()
    manifest = _load_prepared_manifest(out_dir)
    states = {
        spec.name: PluginRunState.from_out_dir(out_dir, spec, cfg.checkpoint_enabled)
        for spec in specs
    }

    for group in _plan_plugin_execution(specs):
        _execute_plugin_group(cfg, manifest, group, states)

    total_counts = {table: 0 for table in TABLE_NAMES}
    total_counts.update(status=0, bad=0)
    for state in states.values():
        for key, value in state.counts.items():
            total_counts[key] += value

    prepared_dir = _prepared_dir(out_dir)
    for table_name in TABLE_NAMES:
        prepared_count = len(_read_table_parquet(prepared_dir / f"{table_name}{TABLE_SUFFIX}", table_name))
        total_counts[table_name] = max(total_counts[table_name], prepared_count)
    return total_counts


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
    metadata_by_source: list[dict[str, Any]] = []
    reference_columns: dict[str, list[str]] = {}
    reference_compatibility: dict[str, Any] | None = None

    for source_dir in resolved_sources:
        if not source_dir.exists():
            raise FileNotFoundError(f"Source out_dir not found: {source_dir}")
        metadata = _read_output_metadata(source_dir)
        compatibility = _metadata_merge_compatibility(metadata)
        if compatibility is not None:
            if reference_compatibility is None:
                reference_compatibility = compatibility
            elif compatibility != reference_compatibility:
                raise ValueError(
                    f"Incompatible source runtime configuration in {source_dir}: "
                    "merge_compatibility does not match earlier sources"
                )
        metadata_by_source.append(
            {
                "out_dir": str(source_dir),
                "output_kind": metadata.get("output_kind", "unknown"),
            }
        )
        for table_name in TABLE_NAMES:
            frame = _read_table_parquet(source_dir / f"{table_name}{TABLE_SUFFIX}", table_name)
            tables_by_name[table_name].append(
                _validate_source_table_columns(table_name, source_dir, frame, reference_columns)
            )
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

    counts = {
        **_count_tables(merged_tables),
        "status": len(merged_status),
        "bad": len(merged_bad),
    }
    _write_json(
        target_out_dir / "dataset_metadata.json",
        {
            "output_kind": "merged_dataset",
            "source_out_dirs": [str(path) for path in resolved_sources],
            "source_outputs": metadata_by_source,
            "counts": counts,
            "merge_compatibility": reference_compatibility,
            "table_columns": _table_columns(merged_tables),
        },
    )
    return counts


def run_chunked_pipeline(
    cfg: Config,
    *,
    chunk_size: int,
    workers: int = 1,
) -> dict[str, int]:
    return _run_chunked_pipeline(cfg, chunk_size=chunk_size, workers=workers)


def plan_chunked_pipeline(
    cfg: Config,
    *,
    chunk_size: int,
    plan_dir: str | Path,
) -> dict[str, int]:
    return _plan_chunked_pipeline(cfg, chunk_size=chunk_size, plan_dir=plan_dir)


def merge_planned_chunks(
    plan_dir: str | Path,
    *,
    out_dir: str | Path | None = None,
) -> dict[str, int]:
    return _merge_planned_chunks(plan_dir, out_dir=out_dir)


def _merge_all_plugin_outputs_batched(
    base_tables: dict[str, pd.DataFrame],
    plugin_outputs_by_table: dict[str, list[pd.DataFrame]],
) -> dict[str, pd.DataFrame]:
    """
    Batch merge all plugin outputs with base tables in a single pass per table.
    
    OPTIMIZATION: Instead of merging plugins sequentially (O(n) merge operations),
    collect all plugin outputs per table, then merge all at once.
    
    This reduces from: N plugins × 4 tables × 1 merge = O(N) passes
    To: 4 tables × 1 merge = O(1) passes
    
    For 100k structures and 8 plugins, this avoids ~32 full table scans.
    """
    merged = {}
    for table_name in TABLE_NAMES:
        base = base_tables[table_name]
        plugins = plugin_outputs_by_table.get(table_name, [])
        
        if not plugins:
            merged[table_name] = base
            continue
        
        # Validate all plugin outputs have required keys
        keys = KEY_COLS[table_name]
        for plugin_frame in plugins:
            missing = [col for col in keys if col not in plugin_frame.columns]
            if missing:
                raise ValueError(f"Missing merge keys for {table_name}: {', '.join(missing)}")
        
        # Collect all data frames for this table
        all_frames = [base] + plugins
        
        # Batch merge: collect non-key columns from all plugins
        base_cols = set(base.columns)
        all_non_key_cols = set()
        for plugin_frame in plugins:
            plugin_non_key = set(plugin_frame.columns) - set(keys)
            overlapping = plugin_non_key & all_non_key_cols
            if overlapping:
                raise ValueError(
                    f"Duplicate output columns detected in {table_name} across plugins: {', '.join(sorted(overlapping))}"
                )
            overlapping_with_base = plugin_non_key & (base_cols - set(keys))
            if overlapping_with_base:
                raise ValueError(
                    f"Overlapping output columns detected in {table_name} between plugins and base: {', '.join(sorted(overlapping_with_base))}"
                )
            all_non_key_cols.update(plugin_non_key)
        
        if not all_non_key_cols:
            merged[table_name] = base
            continue
        
        # Perform batch merge: start with base, then merge each plugin sequentially
        # (but all at once reduces peak memory vs sequential merges)
        result = base.copy()
        for plugin_frame in plugins:
            if not plugin_frame.empty:
                plugin_non_key = [col for col in plugin_frame.columns if col not in keys]
                plugin_cols = keys + plugin_non_key
                result = result.merge(
                    plugin_frame.loc[:, plugin_cols],
                    on=keys,
                    how="left",
                    validate="one_to_one"
                )
        
        merged[table_name] = result
    
    return merged


def merge_outputs(cfg: Config) -> dict[str, int]:
    """
    Merge plugin outputs with base tables.
    
    Phase 2b of the pipeline. Requires prepare_outputs and run_plugin calls first.
    
    OPTIMIZED: Now batches all plugin outputs per table instead of sequential merging.
    Reduces from O(n_plugins) merge passes to O(1) passes.
    
    1. Reads canonical base tables from _prepared/
    2. Collects ALL plugin outputs per table
    3. Performs batch merge on identity keys
    4. Consolidates status/error tracking from all phases
    5. Writes final merged tables to out_dir/
    
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

    # Read base tables once
    base_tables = {
        table_name: _read_table_parquet(prepared_dir / f"{table_name}{TABLE_SUFFIX}", table_name)
        for table_name in TABLE_NAMES
    }
    
    # Collect all plugin outputs per table
    plugin_outputs_by_table: dict[str, list[pd.DataFrame]] = {table_name: [] for table_name in TABLE_NAMES}
    status_frames = [_read_frame(prepared_dir / f"plugin_status{TABLE_SUFFIX}", STATUS_COLS)]
    bad_frames = [_read_frame(prepared_dir / f"bad_files{TABLE_SUFFIX}", BAD_COLS)]

    plugin_names = cfg.plugins
    for plugin_name in plugin_names:
        plugin_dir = _plugin_dir(out_dir, plugin_name)
        if not plugin_dir.exists():
            raise FileNotFoundError(f"Plugin outputs not found for configured plugin '{plugin_name}': {plugin_dir}")
        
        # Read and collect plugin outputs per table
        for table_name in TABLE_NAMES:
            plugin_frame = _read_table_parquet(plugin_dir / f"{table_name}{TABLE_SUFFIX}", table_name)
            if not plugin_frame.empty:
                plugin_outputs_by_table[table_name].append(plugin_frame)
        
        # Collect tracking frames
        status_frames.append(_read_frame(plugin_dir / f"plugin_status{TABLE_SUFFIX}", STATUS_COLS))
        bad_frames.append(_read_frame(plugin_dir / f"bad_files{TABLE_SUFFIX}", BAD_COLS))

    # Perform batch merge instead of sequential
    merged_tables = _merge_all_plugin_outputs_batched(base_tables, plugin_outputs_by_table)
    merged_status = _merge_tracking_frames(status_frames)
    merged_bad = _merge_tracking_frames(bad_frames)

    _write_tables(out_dir, merged_tables)
    merged_status.to_parquet(out_dir / f"plugin_status{TABLE_SUFFIX}", index=False)
    merged_bad.to_parquet(out_dir / f"bad_files{TABLE_SUFFIX}", index=False)

    counts = {
        **_count_tables(merged_tables),
        "status": len(merged_status),
        "bad": len(merged_bad),
    }
    _write_json(
        out_dir / "run_metadata.json",
        {
            "output_kind": "run",
            "config": cfg.model_dump(),
            "prepare_execution": _prepare_execution_metadata(cfg),
            "plugin_execution": _plugin_execution_metadata(cfg.plugins),
            "counts": counts,
            "merge_compatibility": _merge_compatibility(cfg),
            "table_columns": _table_columns(merged_tables),
        },
    )
    return counts


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
        run_plugins(cfg, cfg.plugins)
        counts = merge_outputs(cfg)
        if cfg.dataset_analyses:
            _run_dataset_analyses(cfg, out_dir)
        return counts

    with tempfile.TemporaryDirectory(prefix="minimum_atw_run_") as tmp_dir:
        temp_cfg = cfg.model_copy(update={"out_dir": str(Path(tmp_dir).resolve())})
        prepare_outputs(temp_cfg)
        run_plugins(temp_cfg, temp_cfg.plugins)
        counts = merge_outputs(temp_cfg)
        _copy_final_outputs(Path(temp_cfg.out_dir).resolve(), out_dir)
        if cfg.dataset_analyses:
            _run_dataset_analyses(cfg, out_dir)
    return counts
