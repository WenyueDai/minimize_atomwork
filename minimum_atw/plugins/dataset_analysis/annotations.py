from __future__ import annotations

import pandas as pd

from .base import BaseDatasetPlugin, DatasetAnalysisContext


class DatasetAnnotationsPlugin(BaseDatasetPlugin):
    name = "dataset_annotations"
    analysis_category = "dataset"

    def required_columns(self, _params: dict[str, object]) -> dict[str, list[str]]:
        return {
            "interfaces": ["path"],
            "roles": ["role"],
        }

    def run(self, ctx: DatasetAnalysisContext) -> dict[str, int | str]:
        out_path = ctx.analysis_dir / "dataset_annotations.parquet"
        annotations = dict(ctx.annotations or {})

        rows = [
            {"key": "n_interface_rows", "value": str(int(len(ctx.df_interfaces))), "source": "derived"},
            {"key": "n_unique_structures", "value": str(int(ctx.df_interfaces["path"].nunique())) if "path" in ctx.df_interfaces.columns else "0", "source": "derived"},
            {"key": "n_role_rows", "value": str(int(len(ctx.df_roles))), "source": "derived"},
        ]
        for key in sorted(annotations):
            rows.append({"key": str(key), "value": str(annotations[key]), "source": "config"})

        out = pd.DataFrame(rows, columns=["key", "value", "source"])
        out.to_parquet(out_path, index=False)
        return {
            "n_dataset_annotation_rows": int(len(out)),
            "dataset_annotations_output": str(out_path),
        }
