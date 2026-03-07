from __future__ import annotations

import numpy as np

from .base import BaseManipulation


class CenterOnOriginManipulation(BaseManipulation):
    name = "center_on_origin"
    prefix = "center"
    analysis_category = "structure_manipulation"
    prepare_section = "structure"

    def run(self, ctx):
        if len(ctx.aa) == 0:
            return
        centroid = np.mean(ctx.aa.coord, axis=0)
        ctx.aa.coord = ctx.aa.coord - centroid
        ctx.rebuild_views()
        yield {
            "__table__": "structures",
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "centroid_x": float(centroid[0]),
            "centroid_y": float(centroid[1]),
            "centroid_z": float(centroid[2]),
        }
