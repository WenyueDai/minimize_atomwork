from __future__ import annotations

from .base import BaseQualityControl
from .chain_continuity import ChainContinuityManipulation
from .structure_clashes import StructureClashesManipulation
from ....core.registry import load_registry


def _builtin_quality_controls() -> dict[str, object]:
    return {
        "chain_continuity": ChainContinuityManipulation(),
        "structure_clashes": StructureClashesManipulation(),
    }


PDB_QUALITY_CONTROL_REGISTRY = load_registry(
    builtin_items=_builtin_quality_controls(),
    entry_point_group="minimum_atw.quality_controls",
    label="pdb_quality_control",
    require_prefix=True,
)

__all__ = [
    "BaseQualityControl",
    "ChainContinuityManipulation",
    "PDB_QUALITY_CONTROL_REGISTRY",
    "StructureClashesManipulation",
]
