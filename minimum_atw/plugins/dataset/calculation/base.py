from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(slots=True)
class DatasetAnalysisContext:
    out_dir: Path
    grains: dict[str, pd.DataFrame]
    params: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)

    @property
    def df_interfaces(self) -> pd.DataFrame:
        return self.grains.get("interface", pd.DataFrame())

    @property
    def df_roles(self) -> pd.DataFrame:
        return self.grains.get("role", pd.DataFrame())


@dataclass(slots=True)
class DatasetAnalysisResult:
    dataset_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    pdb_frame: pd.DataFrame = field(default_factory=pd.DataFrame)


class BaseDatasetPlugin:
    name = ""
    extension_class = "dataset_calculation"
    analysis_category = "dataset"

    def required_columns(self, _params: dict[str, Any]) -> dict[str, list[str]]:
        return {}

    def run(self, ctx: DatasetAnalysisContext) -> pd.DataFrame | DatasetAnalysisResult:
        raise NotImplementedError
