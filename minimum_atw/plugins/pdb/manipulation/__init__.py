from __future__ import annotations

from .base import BaseStructureManipulation
from .center import CenterOnOriginManipulation
from .superimpose import SuperimposeToReferenceManipulation
from ....core.registry import load_registry


def _builtin_structure_manipulations() -> dict[str, object]:
    return {
        "center_on_origin": CenterOnOriginManipulation(),
        "superimpose_to_reference": SuperimposeToReferenceManipulation(),
    }


PDB_MANIPULATION_REGISTRY = load_registry(
    builtin_items=_builtin_structure_manipulations(),
    entry_point_group="minimum_atw.structure_manipulations",
    label="pdb_manipulation",
    require_prefix=True,
)

__all__ = [
    "BaseStructureManipulation",
    "CenterOnOriginManipulation",
    "PDB_MANIPULATION_REGISTRY",
    "SuperimposeToReferenceManipulation",
]
