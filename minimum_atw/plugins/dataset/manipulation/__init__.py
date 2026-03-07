from __future__ import annotations

from .base import BaseDatasetManipulation
from ....core.registry import load_registry


DATASET_MANIPULATION_REGISTRY = load_registry(
    builtin_items={},
    entry_point_group="minimum_atw.dataset_manipulations",
    label="dataset_manipulation",
    require_prefix=True,
)

__all__ = [
    "BaseDatasetManipulation",
    "DATASET_MANIPULATION_REGISTRY",
]
