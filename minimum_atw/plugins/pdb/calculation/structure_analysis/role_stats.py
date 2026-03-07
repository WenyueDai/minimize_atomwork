from __future__ import annotations

import biotite.structure as struc
import numpy as np

from ...annotations import role_unique_residue_count
from ....base import RolePlugin, Context


class RoleStatsPlugin(RolePlugin):
    name = "role_stats"
    prefix = "rolstat"

    def run(self, ctx: Context):
        for role_name, role_aa in self.iter_roles(ctx):
            if len(role_aa) == 0:
                continue

            coords = role_aa.coord
            centroid = np.mean(coords, axis=0)
            radius = float(struc.gyration_radius(role_aa))

            yield {
                "grain": "role",
                **self.role_identity_row(ctx, role_name=role_name),
                "n_residues": int(role_unique_residue_count(ctx, role_name)),
                "centroid_x": float(centroid[0]),
                "centroid_y": float(centroid[1]),
                "centroid_z": float(centroid[2]),
                "radius_of_gyration": radius,
            }
