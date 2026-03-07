from __future__ import annotations

from .base import BaseDatasetQualityControl
from ....core.registry import load_registry


DATASET_QUALITY_CONTROL_REGISTRY = load_registry(
    builtin_items={},
    entry_point_group="minimum_atw.dataset_quality_controls",
    label="dataset_quality_control",
    require_prefix=True,
)

__all__ = [
    "BaseDatasetQualityControl",
    "DATASET_QUALITY_CONTROL_REGISTRY",
]
