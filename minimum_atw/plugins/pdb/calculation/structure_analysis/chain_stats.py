from __future__ import annotations

import numpy as np

from ..base import ChainPlugin, Context


class ChainStatsPlugin(ChainPlugin):
    name = "chain_stats"
    prefix = "chstat"

    def run(self, ctx: Context):
        for chain_id, chain_aa in self.iter_chains(ctx):
            if len(chain_aa) == 0:
                continue

            # Calculate basic statistics
            coords = chain_aa.coord
            centroid = np.mean(coords, axis=0)
            radius = np.max(np.linalg.norm(coords - centroid, axis=1))

            yield {
                "grain": "chain",
                **self.chain_identity_row(ctx, chain_id=chain_id),
                "n_residues": int(len(np.unique(chain_aa.res_id))),
                "centroid_x": float(centroid[0]),
                "centroid_y": float(centroid[1]),
                "centroid_z": float(centroid[2]),
                "radius_of_gyration": float(radius),
            }