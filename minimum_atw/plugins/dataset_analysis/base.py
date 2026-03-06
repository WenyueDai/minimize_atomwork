from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(slots=True)
class DatasetAnalysisContext:
    out_dir: Path
    analysis_dir: Path
    df_interfaces: pd.DataFrame
    df_roles: pd.DataFrame
    params: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)


class BaseDatasetPlugin:
    name = ""
    extension_class = "dataset_analysis"
    analysis_category = "dataset"

    def run(self, ctx: DatasetAnalysisContext) -> dict[str, Any]:
        raise NotImplementedError
