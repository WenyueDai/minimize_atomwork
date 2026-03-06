from __future__ import annotations

import numpy as np

from ..base import BasePlugin, Context


class IdentityPlugin(BasePlugin):
    name = "identity"
    prefix = "id"
    table = "structures"

    def run(self, ctx: Context):
        yield {
            "__table__": "structures",
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "n_atoms_total": int(len(ctx.aa)),
            "n_chains": int(len(ctx.chains)),
            "has_nan_coord": bool(np.isnan(ctx.aa.coord).any()) if len(ctx.aa) else True,
        }

        for chain_id, arr in ctx.chains.items():
            yield {
                "__table__": "chains",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "chain_id": chain_id,
                "n_atoms": int(len(arr)),
            }

        for role_name, arr in ctx.roles.items():
            yield {
                "__table__": "roles",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "role": role_name,
                "n_atoms": int(len(arr)),
            }
