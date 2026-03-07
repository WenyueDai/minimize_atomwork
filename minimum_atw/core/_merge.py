"""Internal merge and final-output persistence helpers."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

from .output_files import (
    output_files_from_config,
    output_files_from_metadata,
    pdb_output_path,
    read_output_metadata,
)
from ..runtime.workspace import (
    plugin_bad_path as _plugin_bad_path,
    plugin_pdb_path as _plugin_pdb_path,
    plugin_status_path as _plugin_status_path,
    prepared_dir as _prepared_dir,
    clear_final_outputs as _clear_final_outputs,
)
from ._execute import plugin_execution_metadata as _plugin_execution_metadata
from ._prepare import prepare_execution_metadata as _prepare_execution_metadata
from .config import Config
from .tables import (
    BAD_COLS,
    PDB_TABLE_NAME,
    STATUS_COLS,
    TABLE_SUFFIX,
    count_pdb_rows as _count_pdb_rows,
    merge_pdb_frames as _merge_pdb_frames,
    read_frame as _read_frame,
    read_pdb_table as _read_pdb_table,
    stack_pdb_frames as _stack_pdb_frames,
    write_pdb_table as _write_pdb_table,
)


def _merge_tracking_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_optional_tracking_frame(path: Path, frame: pd.DataFrame) -> None:
    if frame.empty:
        if path.exists():
            path.unlink()
        return
    frame.to_parquet(path, index=False)


def _status_summary(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty or "status" not in frame.columns:
        return {}
    counts = frame["status"].value_counts(dropna=False)
    return {str(status): int(count) for status, count in counts.items()}


def _combine_status_summaries(summaries: list[dict[str, int]]) -> dict[str, int]:
    combined: dict[str, int] = {}
    for summary in summaries:
        for status, count in summary.items():
            combined[status] = combined.get(status, 0) + int(count)
    return combined


def _has_non_ok_status(summary: dict[str, int]) -> bool:
    return any(status != "ok" and count > 0 for status, count in summary.items())


def _status_summary_from_metadata(metadata: dict[str, Any]) -> dict[str, int]:
    raw = metadata.get("status_summary")
    if isinstance(raw, dict):
        return {str(status): int(count) for status, count in raw.items()}
    counts = metadata.get("counts")
    if isinstance(counts, dict):
        total = counts.get("status")
        if total:
            return {"unknown": int(total)}
    return {}


def _write_plugin_status_if_needed(
    path: Path,
    frame: pd.DataFrame,
    *,
    keep_success_records: bool,
) -> None:
    summary = _status_summary(frame)
    if keep_success_records or _has_non_ok_status(summary):
        _write_optional_tracking_frame(path, frame)
        return
    if path.exists():
        path.unlink()


def _table_columns(pdb_frame: pd.DataFrame) -> dict[str, list[str]]:
    return {PDB_TABLE_NAME: list(pdb_frame.columns)}


def _merge_compatibility(config: Config) -> dict[str, Any]:
    return config.merge_compatibility()


def _metadata_merge_compatibility(metadata: dict[str, Any]) -> dict[str, Any] | None:
    compatibility = metadata.get("merge_compatibility")
    if compatibility is not None:
        return compatibility
    raw_config = metadata.get("config")
    if raw_config is None:
        return None
    try:
        return Config(**raw_config).merge_compatibility()
    except Exception:
        return None


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


def merge_outputs(cfg: Config) -> dict[str, int]:
    """Merge prepare and plugin outputs into final tables via LEFT JOIN."""
    out_dir = Path(cfg.out_dir).resolve()
    prepared_dir = _prepared_dir(out_dir)
    if not prepared_dir.exists():
        raise FileNotFoundError(f"Prepared outputs not found: {prepared_dir}")
    output_files = output_files_from_config(cfg)
    _clear_final_outputs(out_dir, cfg=cfg)

    merged_pdb = _read_pdb_table(prepared_dir / f"{PDB_TABLE_NAME}{TABLE_SUFFIX}")
    status_frames = [_read_frame(prepared_dir / f"plugin_status{TABLE_SUFFIX}", STATUS_COLS)]
    bad_frames = [_read_frame(prepared_dir / f"bad_files{TABLE_SUFFIX}", BAD_COLS)]

    for plugin_name in cfg.plugins:
        plugin_pdb = _plugin_pdb_path(out_dir, plugin_name)
        plugin_status = _plugin_status_path(out_dir, plugin_name)
        plugin_bad = _plugin_bad_path(out_dir, plugin_name)
        if not plugin_pdb.exists() and not plugin_status.exists() and not plugin_bad.exists():
            raise FileNotFoundError(
                f"Plugin outputs not found for configured plugin '{plugin_name}' "
                f"in {_plugin_pdb_path(out_dir, plugin_name).parent}"
            )
        merged_pdb = _merge_pdb_frames(merged_pdb, _read_pdb_table(plugin_pdb))
        status_frames.append(_read_frame(plugin_status, STATUS_COLS))
        bad_frames.append(_read_frame(plugin_bad, BAD_COLS))

    merged_status = _merge_tracking_frames(status_frames)
    merged_bad = _merge_tracking_frames(bad_frames)
    status_summary = _status_summary(merged_status)

    _write_pdb_table(out_dir, merged_pdb, filename=output_files["pdb"])
    _write_plugin_status_if_needed(
        out_dir / f"plugin_status{TABLE_SUFFIX}",
        merged_status,
        keep_success_records=cfg.keep_intermediate_outputs or cfg.checkpoint_enabled,
    )
    _write_optional_tracking_frame(out_dir / f"bad_files{TABLE_SUFFIX}", merged_bad)

    counts = {
        **_count_pdb_rows(merged_pdb),
        "status": sum(status_summary.values()),
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
            "status_summary": status_summary,
            "output_files": output_files,
            "merge_compatibility": _merge_compatibility(cfg),
            "table_columns": _table_columns(merged_pdb),
        },
    )
    return counts


def merge_dataset_outputs(source_out_dirs: list[str | Path], out_dir: str | Path) -> dict[str, int]:
    """Stack outputs from multiple runs (chunks) into a single merged dataset."""
    resolved_sources = [Path(path).resolve() for path in source_out_dirs]
    target_out_dir = Path(out_dir).resolve()
    if not resolved_sources:
        raise ValueError("At least one source out_dir is required")
    if target_out_dir in resolved_sources:
        raise ValueError("Target out_dir must be different from all source out_dirs")

    pdb_frames: list[pd.DataFrame] = []
    status_frames: list[pd.DataFrame] = []
    bad_frames: list[pd.DataFrame] = []
    metadata_by_source: list[dict[str, Any]] = []
    source_status_summaries: list[dict[str, int]] = []
    reference_columns: dict[str, list[str]] = {}
    reference_compatibility: dict[str, Any] | None = None
    target_output_files: dict[str, str] | None = None

    for source_dir in resolved_sources:
        if not source_dir.exists():
            raise FileNotFoundError(f"Source out_dir not found: {source_dir}")
        metadata = read_output_metadata(source_dir)
        compatibility = _metadata_merge_compatibility(metadata)
        if compatibility is not None:
            if reference_compatibility is None:
                reference_compatibility = compatibility
            elif compatibility != reference_compatibility:
                warnings.warn(
                    f"Incompatible source runtime configuration in {source_dir}: "
                    "merge_compatibility does not match earlier sources",
                    stacklevel=2,
                )
        metadata_by_source.append(
            {
                "out_dir": str(source_dir),
                "output_kind": metadata.get("output_kind", "unknown"),
                "output_files": output_files_from_metadata(metadata),
            }
        )
        source_output_files = output_files_from_metadata(metadata)
        if target_output_files is None:
            target_output_files = source_output_files
        frame = _read_pdb_table(pdb_output_path(source_dir, metadata=metadata))
        pdb_frames.append(_validate_source_table_columns(PDB_TABLE_NAME, source_dir, frame, reference_columns))
        source_status_frame = _read_frame(source_dir / f"plugin_status{TABLE_SUFFIX}", STATUS_COLS)
        status_frames.append(source_status_frame)
        source_status_summaries.append(
            _status_summary(source_status_frame) or _status_summary_from_metadata(metadata)
        )
        bad_frames.append(_read_frame(source_dir / f"bad_files{TABLE_SUFFIX}", BAD_COLS))

    merged_pdb = _stack_pdb_frames(pdb_frames)
    merged_status = _merge_tracking_frames(status_frames)
    merged_bad = _merge_tracking_frames(bad_frames)
    status_summary = _combine_status_summaries(source_status_summaries)
    target_output_files = target_output_files or {"pdb": "pdb.parquet", "dataset": "dataset.parquet"}
    _clear_final_outputs(target_out_dir)

    _write_pdb_table(target_out_dir, merged_pdb, filename=target_output_files["pdb"])
    _write_plugin_status_if_needed(
        target_out_dir / f"plugin_status{TABLE_SUFFIX}",
        merged_status,
        keep_success_records=False,
    )
    _write_optional_tracking_frame(target_out_dir / f"bad_files{TABLE_SUFFIX}", merged_bad)

    counts = {
        **_count_pdb_rows(merged_pdb),
        "status": sum(status_summary.values()),
        "bad": len(merged_bad),
    }
    _write_json(
        target_out_dir / "dataset_metadata.json",
        {
            "output_kind": "merged_dataset",
            "source_out_dirs": [str(path) for path in resolved_sources],
            "source_outputs": metadata_by_source,
            "counts": counts,
            "status_summary": status_summary,
            "output_files": target_output_files,
            "merge_compatibility": reference_compatibility,
            "table_columns": _table_columns(merged_pdb),
        },
    )
    return counts
