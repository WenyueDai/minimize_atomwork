from __future__ import annotations

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
    PDB_GRAINS,
    PDB_KEY_COLS,
    count_pdb_rows,
    empty_pdb_frame,
    merge_pdb_frames,
    read_pdb_table,
    stack_pdb_frames,
    write_pdb_table,
)
from . import DATASET_CALCULATION_REGISTRY, DEFAULT_DATASET_CALCULATIONS, DatasetAnalysisContext, DatasetAnalysisResult
from ....core.registry import instantiate_unit


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
    legacy_filename = {"interface": "interfaces.parquet", "role": "roles.parquet"}.get(grain, f"{grain}.parquet")
    legacy_path = out_dir / legacy_filename
    if not path.exists() and legacy_path.exists():
        if not columns:
            return pd.read_parquet(legacy_path)
        parquet = pq.ParquetFile(legacy_path)
        available = set(parquet.schema.names)
        present = [column for column in columns if column in available]
        missing = [column for column in columns if column not in available]
        if not present:
            frame = pd.DataFrame(index=range(parquet.metadata.num_rows))
        else:
            frame = pd.read_parquet(legacy_path, columns=present)
        for column in missing:
            frame[column] = pd.NA
        return frame.loc[:, [column for column in columns if column in frame.columns]].reset_index(drop=True)
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


def _legacy_grain_path(out_dir: Path, grain: str) -> Path:
    legacy_filename = {"interface": "interfaces.parquet", "role": "roles.parquet"}.get(grain, f"{grain}.parquet")
    return out_dir / legacy_filename


def _load_legacy_pdb_table(out_dir: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for grain in PDB_GRAINS:
        legacy_path = _legacy_grain_path(out_dir, grain)
        if not legacy_path.exists():
            continue
        frame = pd.read_parquet(legacy_path).copy()
        frame["grain"] = grain
        for key in PDB_KEY_COLS:
            if key not in frame.columns:
                frame[key] = ""
            else:
                frame[key] = frame[key].fillna("")
        ordered = [column for column in PDB_KEY_COLS if column in frame.columns]
        ordered.extend(column for column in frame.columns if column not in ordered)
        frames.append(frame.loc[:, ordered])
    if not frames:
        return empty_pdb_frame()
    return stack_pdb_frames(frames)


def _load_existing_pdb_table(out_dir: Path, metadata: dict[str, object]) -> pd.DataFrame:
    path = pdb_output_path(out_dir, metadata=metadata)
    if path.exists():
        return read_pdb_table(path)
    return _load_legacy_pdb_table(out_dir)


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


def analyze_dataset_outputs(
    out_dir: Path,
    *,
    dataset_analyses: tuple[str, ...] | None = None,
    dataset_analysis_params: dict[str, dict[str, object]] | None = None,
    dataset_annotations: dict[str, str] | None = None,
) -> dict[str, int | str]:
    out_dir = Path(out_dir).resolve()
    print(f"[dataset] start out_dir={out_dir}", flush=True)
    metadata = _read_dataset_metadata(out_dir)
    pdb_path = pdb_output_path(out_dir, metadata=metadata)
    legacy_paths = [out_dir / "interfaces.parquet", out_dir / "roles.parquet"]
    if not pdb_path.exists() and not any(path.exists() for path in legacy_paths):
        raise FileNotFoundError(f"Missing pdb table or legacy grain tables in: {out_dir}")

    analysis_dir = out_dir / "dataset_analysis"
    if analysis_dir.exists():
        shutil.rmtree(analysis_dir)
    dataset_path = dataset_output_path(out_dir, metadata=metadata)
    if dataset_path.exists():
        dataset_path.unlink()

    analysis_names = tuple(dataset_analyses or DEFAULT_DATASET_CALCULATIONS)
    metadata = _read_dataset_metadata(out_dir)
    metadata_counts = metadata.get("counts") if isinstance(metadata.get("counts"), dict) else {}
    n_interfaces = metadata_counts.get("interfaces")
    if n_interfaces is None:
        n_interfaces = len(_read_output_table(out_dir, "interface", columns=["path"]))
    summary: dict[str, int | str] = {
        "n_interfaces": int(n_interfaces),
        "dataset_analyses": ",".join(analysis_names),
    }
    cache: dict[tuple[str, tuple[str, ...]], pd.DataFrame] = {}
    analysis_frames: list[pd.DataFrame] = []
    pdb_update_frames: list[pd.DataFrame] = []
    for analysis_name in analysis_names:
        print(f"[dataset:{analysis_name}] start", flush=True)
        if analysis_name not in DATASET_CALCULATION_REGISTRY:
            raise ValueError(
                f"Unknown dataset analysis '{analysis_name}'. Available: {sorted(DATASET_CALCULATION_REGISTRY)}"
            )
        plugin = instantiate_unit(DATASET_CALCULATION_REGISTRY[analysis_name])
        params = dict((dataset_analysis_params or {}).get(analysis_name, {}))
        required = plugin.required_columns(params) if hasattr(plugin, "required_columns") else {}

        def load_table(table_name: str) -> pd.DataFrame:
            columns = tuple(required.get(table_name, []))
            cache_key = (table_name, columns)
            if cache_key not in cache:
                cache[cache_key] = _read_output_table(
                    out_dir,
                    table_name,
                    columns=list(columns) if columns else None,
                )
            return cache[cache_key]

        grain_names = list(required.keys()) if required else ["interface", "role"]
        grains = {grain_name: load_table(grain_name) for grain_name in grain_names}
        analysis_ctx = DatasetAnalysisContext(
            out_dir=out_dir,
            grains=grains,
            params=params,
            annotations=dict(dataset_annotations or {}),
        )
        dataset_frame, pdb_frame = _normalize_analysis_result(analysis_name, plugin.run(analysis_ctx))
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
        for pdb_frame in pdb_update_frames:
            merged_pdb = merge_pdb_frames(merged_pdb, pdb_frame)
        write_pdb_table(
            out_dir,
            merged_pdb,
            filename=pdb_output_path(out_dir, metadata=metadata).name,
        )
        _write_updated_metadata(out_dir, metadata, pdb_frame=merged_pdb)
    summary["n_dataset_rows"] = int(len(combined))
    summary["dataset_output"] = str(dataset_path)
    print(
        f"[dataset] complete dataset_rows={summary['n_dataset_rows']} "
        f"dataset_output={dataset_path.name}",
        flush=True,
    )
    return summary
