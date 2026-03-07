from __future__ import annotations

from .base import BaseDatasetManipulation
from .superimpose import SuperimposeHomologyManipulation
from ....core.registry import load_registry


def _builtin_dataset_manipulations() -> dict[str, object]:
    return {
        "superimpose_homology": SuperimposeHomologyManipulation(),
    }


DATASET_MANIPULATION_REGISTRY = load_registry(
    builtin_items=_builtin_dataset_manipulations(),
    entry_point_group="minimum_atw.dataset_manipulations",
    label="dataset_manipulation",
    require_prefix=True,
)

__all__ = [
    "BaseDatasetManipulation",
    "DATASET_MANIPULATION_REGISTRY",
    "SuperimposeHomologyManipulation",
]
