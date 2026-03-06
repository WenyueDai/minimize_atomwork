from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import DATASET_ANALYSIS_REGISTRY, DEFAULT_DATASET_ANALYSES, DatasetAnalysisContext
from ...registry import instantiate_unit


def analyze_dataset_outputs(
    out_dir: Path,
    *,
    dataset_analyses: tuple[str, ...] | None = None,
    dataset_annotations: dict[str, str] | None = None,
) -> dict[str, int | str]:
    out_dir = Path(out_dir).resolve()
    interfaces_path = out_dir / "interfaces.parquet"
    if not interfaces_path.exists():
        raise FileNotFoundError(f"Missing interfaces table: {interfaces_path}")

    analysis_dir = out_dir / "dataset_analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    df_interfaces = pd.read_parquet(interfaces_path)
    roles_path = out_dir / "roles.parquet"
    df_roles = pd.read_parquet(roles_path) if roles_path.exists() else pd.DataFrame()
    analysis_names = tuple(dataset_analyses or DEFAULT_DATASET_ANALYSES)
    ctx = DatasetAnalysisContext(
        out_dir=out_dir,
        analysis_dir=analysis_dir,
        df_interfaces=df_interfaces,
        df_roles=df_roles,
        params={"dataset_analyses": list(analysis_names)},
        annotations=dict(dataset_annotations or {}),
    )

    summary: dict[str, int | str] = {
        "n_interfaces": int(len(df_interfaces)),
        "dataset_analyses": ",".join(analysis_names),
    }
    for analysis_name in analysis_names:
        if analysis_name not in DATASET_ANALYSIS_REGISTRY:
            raise ValueError(
                f"Unknown dataset analysis '{analysis_name}'. Available: {sorted(DATASET_ANALYSIS_REGISTRY)}"
            )
        result = instantiate_unit(DATASET_ANALYSIS_REGISTRY[analysis_name]).run(ctx)
        if result:
            summary.update({str(key): value for key, value in result.items()})

    (analysis_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary
