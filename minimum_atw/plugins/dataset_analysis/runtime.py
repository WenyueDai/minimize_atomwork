from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from . import DATASET_ANALYSIS_REGISTRY, DEFAULT_DATASET_ANALYSES, DatasetAnalysisContext
from ...core.registry import instantiate_unit


def _read_output_table(
    out_dir: Path,
    table_name: str,
    *,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    path = out_dir / f"{table_name}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=columns or [])
    if not columns:
        return pd.read_parquet(path)

    parquet = pq.ParquetFile(path)
    available = set(parquet.schema.names)
    present = [column for column in columns if column in available]
    missing = [column for column in columns if column not in available]
    if not present:
        frame = pd.DataFrame(index=range(parquet.metadata.num_rows))
    else:
        frame = pd.read_parquet(path, columns=present)
    for column in missing:
        frame[column] = pd.NA
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
    interfaces_path = out_dir / "interfaces.parquet"
    if not interfaces_path.exists():
        raise FileNotFoundError(f"Missing interfaces table: {interfaces_path}")

    analysis_dir = out_dir / "dataset_analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    analysis_names = tuple(dataset_analyses or DEFAULT_DATASET_ANALYSES)
    interface_counts = _read_output_table(out_dir, "interfaces", columns=["path"])
    summary: dict[str, int | str] = {
        "n_interfaces": int(len(interface_counts)),
        "dataset_analyses": ",".join(analysis_names),
    }
    cache: dict[tuple[str, tuple[str, ...]], pd.DataFrame] = {}
    for analysis_name in analysis_names:
        if analysis_name not in DATASET_ANALYSIS_REGISTRY:
            raise ValueError(
                f"Unknown dataset analysis '{analysis_name}'. Available: {sorted(DATASET_ANALYSIS_REGISTRY)}"
            )
        plugin = instantiate_unit(DATASET_ANALYSIS_REGISTRY[analysis_name])
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

        analysis_ctx = DatasetAnalysisContext(
            out_dir=out_dir,
            analysis_dir=analysis_dir,
            df_interfaces=load_table("interfaces"),
            df_roles=load_table("roles"),
            params=params,
            annotations=dict(dataset_annotations or {}),
        )
        result = plugin.run(analysis_ctx)
        if result:
            summary.update({str(key): value for key, value in result.items()})

    (analysis_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary
