from __future__ import annotations

import numpy as np

from ..base import RolePlugin, Context


class RoleStatsPlugin(RolePlugin):
    name = "role_stats"
    prefix = "rolstat"

    def run(self, ctx: Context):
        for role_name, role_aa in self.iter_roles(ctx):
            if len(role_aa) == 0:
                continue

            # Calculate basic statistics
            coords = role_aa.coord
            centroid = np.mean(coords, axis=0)
            radius = np.max(np.linalg.norm(coords - centroid, axis=1))

            yield {
                "__table__": "roles",
                **self.role_identity_row(ctx, role_name=role_name),
                "n_residues": int(len(np.unique(role_aa.res_id))),
                "centroid_x": float(centroid[0]),
                "centroid_y": float(centroid[1]),
                "centroid_z": float(centroid[2]),
                "radius_of_gyration": float(radius),
            }