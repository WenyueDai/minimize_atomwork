from __future__ import annotations

from .base import BaseManipulation
from .center import CenterOnOriginManipulation
from .superimpose import SuperimposeHomologyManipulation
from ...core.registry import load_registry


def _builtin_manipulations() -> dict[str, object]:
    return {
        "center_on_origin": CenterOnOriginManipulation(),
        "superimpose_homology": SuperimposeHomologyManipulation(),
    }


MANIPULATION_REGISTRY = load_registry(
    builtin_items=_builtin_manipulations(),
    entry_point_group="minimum_atw.manipulations",
    label="manipulation",
    require_prefix=True,
)

__all__ = [
    "BaseManipulation",
    "CenterOnOriginManipulation",
    "SuperimposeHomologyManipulation",
    "MANIPULATION_REGISTRY",
]
