from __future__ import annotations

import json

from ...annotations import role_sequences_by_chain
from ....base import Context, RolePlugin


class RoleSequencesPlugin(RolePlugin):
    name = "role_sequences"
    prefix = "rolseq"

    def run(self, ctx: Context):
        for role_name, role_aa in self.iter_roles(ctx):
            seq_by_chain = role_sequences_by_chain(ctx, role_name)
            chain_ids = sorted(seq_by_chain)
            total_length = sum(len(sequence) for sequence in seq_by_chain.values())
            concatenated = "".join(seq_by_chain[chain_id] for chain_id in chain_ids)
            yield {
                "grain": "role",
                **self.role_identity_row(ctx, role_name=role_name),
                "chain_ids": ";".join(chain_ids),
                "n_chains": int(len(chain_ids)),
                "sequence_length_total": int(total_length),
                "sequence": concatenated if len(chain_ids) == 1 else "",
                "sequence_by_chain": json.dumps(seq_by_chain, sort_keys=True, separators=(",", ":")),
            }
