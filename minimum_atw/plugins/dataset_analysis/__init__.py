from __future__ import annotations

from .base import BaseDatasetPlugin, DatasetAnalysisContext
from .annotations import DatasetAnnotationsPlugin
from .cdr_entropy import CDREntropyPlugin
from .interface_summary import InterfaceSummaryPlugin
from ...registry import load_registry


def _builtin_dataset_analyses() -> dict[str, object]:
    return {
        "cdr_entropy": CDREntropyPlugin(),
        "dataset_annotations": DatasetAnnotationsPlugin(),
        "interface_summary": InterfaceSummaryPlugin(),
    }


DATASET_ANALYSIS_REGISTRY = load_registry(
    builtin_items=_builtin_dataset_analyses(),
    entry_point_group="minimum_atw.dataset_analyses",
    label="dataset analysis",
)
DEFAULT_DATASET_ANALYSES = ("interface_summary",)

__all__ = [
    "BaseDatasetPlugin",
    "DatasetAnalysisContext",
    "CDREntropyPlugin",
    "DatasetAnnotationsPlugin",
    "InterfaceSummaryPlugin",
    "DATASET_ANALYSIS_REGISTRY",
    "DEFAULT_DATASET_ANALYSES",
]
