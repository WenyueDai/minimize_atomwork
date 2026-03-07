from __future__ import annotations

import numpy as np
import biotite.structure as struc

from ..annotations import residue_starts
from .base import BaseQualityControl


def _count_residue_id_gaps(arr) -> int:
    starts = residue_starts(arr)
    if starts.size < 2:
        return 0
    residue_ids = np.asarray(arr.res_id[starts], dtype=int)
    gaps = residue_ids[1:] - residue_ids[:-1]
    return int(np.count_nonzero(gaps > 1))


class ChainContinuityManipulation(BaseQualityControl):
    name = "chain_continuity"
    prefix = "continuity"

    def run(self, ctx):
        for chain_id, arr in ctx.chains.items():
            if arr is None or len(arr) == 0:
                continue
            try:
                residue_gap_breaks = _count_residue_id_gaps(arr)
                discontinuities = np.asarray(struc.check_backbone_continuity(arr), dtype=int)
                interior_discontinuities = discontinuities[discontinuities < (len(arr) - 1)]
                backbone_breaks = int(interior_discontinuities.size > 0)
                n_breaks = residue_gap_breaks if residue_gap_breaks > 0 else backbone_breaks
                has_break = bool(n_breaks > 0)
            except Exception:
                has_break = True
                n_breaks = -1

            yield {
                "grain": "chain",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "chain_id": str(chain_id),
                "has_break": bool(has_break),
                "n_breaks": int(n_breaks),
            }
