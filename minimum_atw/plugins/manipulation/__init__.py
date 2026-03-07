from __future__ import annotations

from .base import BaseManipulation
from .chain_continuity import ChainContinuityManipulation
from .center import CenterOnOriginManipulation
from .structure_clashes import StructureClashesManipulation
from .superimpose import SuperimposeHomologyManipulation
from ...core.registry import load_registry


def _builtin_manipulations() -> dict[str, object]:
    return {
        "chain_continuity": ChainContinuityManipulation(),
        "center_on_origin": CenterOnOriginManipulation(),
        "structure_clashes": StructureClashesManipulation(),
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
    "ChainContinuityManipulation",
    "CenterOnOriginManipulation",
    "SuperimposeHomologyManipulation",
    "StructureClashesManipulation",
    "MANIPULATION_REGISTRY",
]
