from __future__ import annotations

from dataclasses import dataclass
import json
import shutil
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ....core.output_files import (
    DATASET_METADATA_NAME,
    RUN_METADATA_NAME,
    dataset_output_path,
    pdb_output_path,
    read_output_metadata,
)
from ....core.tables import (
    count_pdb_rows,
    empty_pdb_frame,
    merge_pdb_frames_bulk,
    read_pdb_table,
    write_pdb_table,
)
from . import DATASET_CALCULATION_REGISTRY, DEFAULT_DATASET_CALCULATIONS, DatasetAnalysisContext, DatasetAnalysisResult
from ....core.registry import instantiate_unit
from ....runtime.workspace import prepared_dir as _prepared_dir


@dataclass(frozen=True)
class _DatasetAnalysisSpec:
    name: str
    plugin: object
    params: dict[str, object]
    required: dict[str, tuple[str, ...] | None]


def _read_dataset_metadata(out_dir: Path) -> dict[str, object]:
    return read_output_metadata(out_dir)


def _read_output_table(
    out_dir: Path,
    grain: str,
    *,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    metadata = _read_dataset_metadata(out_dir)
    path = pdb_output_path(out_dir, metadata=metadata)
    if not path.exists():
        return pd.DataFrame(columns=columns or [])
    if not columns:
        return pq.read_table(path, filters=[("grain", "=", grain)]).to_pandas().reset_index(drop=True)

    requested = list(dict.fromkeys(["grain", *columns]))
    parquet = pq.ParquetFile(path)
    available = set(parquet.schema.names)
    present = [column for column in requested if column in available]
    missing = [column for column in requested if column not in available]

    if not present:
        frame = pd.DataFrame(columns=requested)
    else:
        frame = pq.read_table(path, columns=present, filters=[("grain", "=", grain)]).to_pandas()
    for column in missing:
        frame[column] = pd.NA
    if "grain" not in frame.columns:
        frame["grain"] = grain
    ordered = [column for column in columns if column in frame.columns]
    return frame.loc[:, ordered].reset_index(drop=True)


def _load_existing_pdb_table(out_dir: Path, metadata: dict[str, object]) -> pd.DataFrame:
    path = pdb_output_path(out_dir, metadata=metadata)
    if path.exists():
        return read_pdb_table(path)
    return empty_pdb_frame()


def _metadata_path(out_dir: Path) -> Path | None:
    for filename in (RUN_METADATA_NAME, DATASET_METADATA_NAME):
        path = out_dir / filename
        if path.exists():
            return path
    return None


def _write_updated_metadata(
    out_dir: Path,
    metadata: dict[str, object],
    *,
    pdb_frame: pd.DataFrame | None = None,
) -> None:
    metadata_path = _metadata_path(out_dir)
    if metadata_path is None:
        return
    payload = dict(metadata or {})
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    merged_counts = {str(key): int(value) for key, value in counts.items()}
    if pdb_frame is not None:
        merged_counts.update(count_pdb_rows(pdb_frame))
        payload["table_columns"] = {"pdb": list(pdb_frame.columns)}
    payload["counts"] = merged_counts
    metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _normalize_analysis_result(
    analysis_name: str,
    result: pd.DataFrame | DatasetAnalysisResult | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if result is None:
        return pd.DataFrame(), empty_pdb_frame()
    if isinstance(result, DatasetAnalysisResult):
        dataset_frame = result.dataset_frame if isinstance(result.dataset_frame, pd.DataFrame) else pd.DataFrame()
        pdb_frame = result.pdb_frame if isinstance(result.pdb_frame, pd.DataFrame) else empty_pdb_frame()
        return dataset_frame.copy(), pdb_frame.copy()
    if isinstance(result, pd.DataFrame):
        return result.copy(), empty_pdb_frame()
    raise TypeError(
        f"Dataset analysis '{analysis_name}' must return a pandas DataFrame or DatasetAnalysisResult"
    )


def _cleanup_prepared_outputs(out_dir: Path) -> bool:
    prepared = _prepared_dir(out_dir)
    if not prepared.exists():
        return False
    shutil.rmtree(prepared)
    return True


def _normalize_required_columns(required: dict[str, list[str]] | None) -> dict[str, tuple[str, ...] | None]:
    if not required:
        return {"interface": None, "role": None}
    normalized: dict[str, tuple[str, ...] | None] = {}
    for grain, columns in dict(required).items():
        if not columns:
            normalized[str(grain)] = None
            continue
        normalized[str(grain)] = tuple(dict.fromkeys(str(column) for column in columns))
    return normalized


def _collect_analysis_specs(
    analysis_names: tuple[str, ...],
    dataset_analysis_params: dict[str, dict[str, object]] | None,
) -> list[_DatasetAnalysisSpec]:
    specs: list[_DatasetAnalysisSpec] = []
    for analysis_name in analysis_names:
        if analysis_name not in DATASET_CALCULATION_REGISTRY:
            raise ValueError(
                f"Unknown dataset analysis '{analysis_name}'. Available: {sorted(DATASET_CALCULATION_REGISTRY)}"
            )
        plugin = instantiate_unit(DATASET_CALCULATION_REGISTRY[analysis_name])
        params = dict((dataset_analysis_params or {}).get(analysis_name, {}))
        required = plugin.required_columns(params) if hasattr(plugin, "required_columns") else {}
        specs.append(
            _DatasetAnalysisSpec(
                name=analysis_name,
                plugin=plugin,
                params=params,
                required=_normalize_required_columns(required),
            )
        )
    return specs


def _union_required_columns(specs: list[_DatasetAnalysisSpec]) -> dict[str, tuple[str, ...] | None]:
    combined: dict[str, list[str] | None] = {}
    for spec in specs:
        for grain, columns in spec.required.items():
            if grain not in combined:
                combined[grain] = None if columns is None else list(columns)
                continue
            if combined[grain] is None or columns is None:
                combined[grain] = None
                continue
            existing = combined[grain]
            assert existing is not None
            for column in columns:
                if column not in existing:
                    existing.append(column)
    return {
        grain: None if columns is None else tuple(columns)
        for grain, columns in combined.items()
    }


def _load_grain_frames(
    out_dir: Path,
    requested: dict[str, tuple[str, ...] | None],
) -> dict[str, pd.DataFrame]:
    return {
        grain: _read_output_table(out_dir, grain, columns=list(columns) if columns is not None else None)
        for grain, columns in requested.items()
    }


def _select_analysis_grains(
    loaded_grains: dict[str, pd.DataFrame],
    required: dict[str, tuple[str, ...] | None],
) -> dict[str, pd.DataFrame]:
    selected: dict[str, pd.DataFrame] = {}
    for grain, columns in required.items():
        frame = loaded_grains.get(grain, pd.DataFrame())
        if columns is None:
            selected[grain] = frame.copy()
            continue
        present = [column for column in columns if column in frame.columns]
        missing = [column for column in columns if column not in frame.columns]
        subset = frame.loc[:, present].copy() if present else pd.DataFrame(index=range(len(frame)))
        for column in missing:
            subset[column] = pd.NA
        selected[grain] = subset.loc[:, list(columns)].reset_index(drop=True)
    return selected


def analyze_dataset_outputs(
    out_dir: Path,
    *,
    dataset_analyses: tuple[str, ...] | None = None,
    dataset_analysis_params: dict[str, dict[str, object]] | None = None,
    dataset_annotations: dict[str, str] | None = None,
    reference_dataset_dir: str | None = None,
    cleanup_prepared_after_dataset_analysis: bool = False,
) -> dict[str, int | str]:
    out_dir = Path(out_dir).resolve()
    print(f"[dataset] start out_dir={out_dir}", flush=True)
    metadata = _read_dataset_metadata(out_dir)
    pdb_path = pdb_output_path(out_dir, metadata=metadata)
    if not pdb_path.exists():
        raise FileNotFoundError(f"Missing pdb table in: {out_dir}")

    analysis_dir = out_dir / "dataset_analysis"
    if analysis_dir.exists():
        shutil.rmtree(analysis_dir)
    dataset_path = dataset_output_path(out_dir, metadata=metadata)
    if dataset_path.exists():
        dataset_path.unlink()

    analysis_names = tuple(dataset_analyses or DEFAULT_DATASET_CALCULATIONS)
    metadata = _read_dataset_metadata(out_dir)
    metadata_counts = metadata.get("counts") if isinstance(metadata.get("counts"), dict) else {}
    analysis_specs = _collect_analysis_specs(analysis_names, dataset_analysis_params)
    requested_grains = _union_required_columns(analysis_specs)
    loaded_grains = _load_grain_frames(out_dir, requested_grains)
    n_interfaces = metadata_counts.get("interfaces")
    if n_interfaces is None:
        interface_frame = loaded_grains.get("interface")
        if interface_frame is not None:
            n_interfaces = len(interface_frame)
        else:
            n_interfaces = len(_read_output_table(out_dir, "interface", columns=["path"]))
    summary: dict[str, int | str] = {
        "n_interfaces": int(n_interfaces),
        "dataset_analyses": ",".join(analysis_names),
    }
    if reference_dataset_dir is not None:
        ref_dir = Path(reference_dataset_dir).resolve()
        reference_loaded_grains = _load_grain_frames(ref_dir, requested_grains)
    else:
        reference_loaded_grains = {}
    analysis_frames: list[pd.DataFrame] = []
    pdb_update_frames: list[pd.DataFrame] = []
    for spec in analysis_specs:
        analysis_name = spec.name
        print(f"[dataset:{analysis_name}] start", flush=True)
        grains = _select_analysis_grains(loaded_grains, spec.required)
        reference_grains = _select_analysis_grains(reference_loaded_grains, spec.required) if reference_loaded_grains else {}
        analysis_ctx = DatasetAnalysisContext(
            out_dir=out_dir,
            grains=grains,
            params=spec.params,
            annotations=dict(dataset_annotations or {}),
            reference_grains=reference_grains,
        )
        dataset_frame, pdb_frame = _normalize_analysis_result(analysis_name, spec.plugin.run(analysis_ctx))
        if "analysis" in dataset_frame.columns:
            dataset_frame["analysis"] = dataset_frame["analysis"].fillna(str(analysis_name)).astype(str)
        elif not dataset_frame.empty:
            dataset_frame.insert(0, "analysis", str(analysis_name))
        summary[f"n_{analysis_name}_dataset_rows"] = int(len(dataset_frame))
        summary[f"n_{analysis_name}_pdb_rows"] = int(len(pdb_frame))
        summary[f"n_{analysis_name}_rows"] = int(len(dataset_frame) + len(pdb_frame))
        if not dataset_frame.empty:
            analysis_frames.append(dataset_frame)
        if not pdb_frame.empty:
            pdb_update_frames.append(pdb_frame)
        print(
            f"[dataset:{analysis_name}] finish dataset_rows={len(dataset_frame)} pdb_rows={len(pdb_frame)}",
            flush=True,
        )

    if analysis_frames:
        combined = pd.concat(analysis_frames, ignore_index=True, sort=False)
    else:
        combined = pd.DataFrame(columns=["analysis"])
    combined.to_parquet(dataset_path, index=False)
    if pdb_update_frames:
        merged_pdb = _load_existing_pdb_table(out_dir, metadata)
        merged_pdb = merge_pdb_frames_bulk(merged_pdb, pdb_update_frames)
        write_pdb_table(
            out_dir,
            merged_pdb,
            filename=pdb_output_path(out_dir, metadata=metadata).name,
        )
        _write_updated_metadata(out_dir, metadata, pdb_frame=merged_pdb)
    summary["n_dataset_rows"] = int(len(combined))
    summary["dataset_output"] = str(dataset_path)
    cleaned_prepared = False
    if cleanup_prepared_after_dataset_analysis:
        cleaned_prepared = _cleanup_prepared_outputs(out_dir)
    summary["cleaned_prepared_outputs"] = int(cleaned_prepared)
    print(
        f"[dataset] complete dataset_rows={summary['n_dataset_rows']} "
        f"dataset_output={dataset_path.name}",
        flush=True,
    )
    return summary
