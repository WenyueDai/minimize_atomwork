from __future__ import annotations

from .quality_control import PDB_QUALITY_CONTROL_REGISTRY
from .manipulation import PDB_MANIPULATION_REGISTRY

# Unified prepare-phase registry: QC plugins run first (quality_control section),
# then structure manipulations (structure section). Ordering is governed by each
# plugin's `prepare_section` attribute, not by registry position.
PDB_PREPARE_REGISTRY: dict[str, object] = {
    **PDB_QUALITY_CONTROL_REGISTRY,
    **PDB_MANIPULATION_REGISTRY,
}

__all__ = ["PDB_PREPARE_REGISTRY"]
