from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ....core.output_files import dataset_output_path, pdb_output_path, read_output_metadata
from . import DATASET_CALCULATION_REGISTRY, DEFAULT_DATASET_CALCULATIONS, DatasetAnalysisContext
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


def analyze_dataset_outputs(
    out_dir: Path,
    *,
    dataset_analyses: tuple[str, ...] | None = None,
    dataset_analysis_params: dict[str, dict[str, object]] | None = None,
    dataset_annotations: dict[str, str] | None = None,
) -> dict[str, int | str]:
    out_dir = Path(out_dir).resolve()
    metadata = _read_dataset_metadata(out_dir)
    pdb_path = pdb_output_path(out_dir, metadata=metadata)
    legacy_interfaces_path = out_dir / "interfaces.parquet"
    if not pdb_path.exists() and not legacy_interfaces_path.exists():
        raise FileNotFoundError(f"Missing pdb table: {pdb_path}")

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
    for analysis_name in analysis_names:
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
        frame = plugin.run(analysis_ctx)
        if frame is None:
            frame = pd.DataFrame()
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"Dataset analysis '{analysis_name}' must return a pandas DataFrame")
        frame = frame.copy()
        if "analysis" in frame.columns:
            frame["analysis"] = frame["analysis"].fillna(str(analysis_name)).astype(str)
        else:
            frame.insert(0, "analysis", str(analysis_name))
        summary[f"n_{analysis_name}_rows"] = int(len(frame))
        if not frame.empty:
            analysis_frames.append(frame)

    if analysis_frames:
        combined = pd.concat(analysis_frames, ignore_index=True, sort=False)
    else:
        combined = pd.DataFrame(columns=["analysis"])
    combined.to_parquet(dataset_path, index=False)
    summary["n_dataset_rows"] = int(len(combined))
    summary["dataset_output"] = str(dataset_path)
    return summary
