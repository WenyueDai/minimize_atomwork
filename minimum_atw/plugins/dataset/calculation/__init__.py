from __future__ import annotations

from .annotations import DatasetAnnotationsPlugin
from .base import BaseDatasetPlugin, DatasetAnalysisContext
from .cdr_entropy import CDREntropyPlugin
from .interface_summary import InterfaceSummaryPlugin
from ....core.registry import load_registry


def _builtin_dataset_calculations() -> dict[str, object]:
    return {
        "cdr_entropy": CDREntropyPlugin(),
        "dataset_annotations": DatasetAnnotationsPlugin(),
        "interface_summary": InterfaceSummaryPlugin(),
    }


DATASET_CALCULATION_REGISTRY = load_registry(
    builtin_items=_builtin_dataset_calculations(),
    entry_point_group="minimum_atw.dataset_analyses",
    label="dataset_calculation",
)
DEFAULT_DATASET_CALCULATIONS = ("interface_summary",)

__all__ = [
    "BaseDatasetPlugin",
    "DatasetAnalysisContext",
    "CDREntropyPlugin",
    "DATASET_CALCULATION_REGISTRY",
    "DEFAULT_DATASET_CALCULATIONS",
    "DatasetAnnotationsPlugin",
    "InterfaceSummaryPlugin",
]
