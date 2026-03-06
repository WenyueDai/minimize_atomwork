from __future__ import annotations

from ..base import Context
from .base import AntibodyPluginBase
from .antibody_numbering import imgt_cdr_lengths


class AntibodyCDRLengthsPlugin(AntibodyPluginBase):
    name = "antibody_cdr_lengths"
    prefix = "abcdr"

    def run(self, ctx: Context):
        for role_name, chain_ids, sequence in self.iter_antibody_roles(ctx):
            lengths = imgt_cdr_lengths(sequence)
            yield {
                "__table__": "roles",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "role": role_name,
                "chain_ids": ";".join(chain_ids),
                "sequence_length": int(len(sequence)),
                "cdr1_length": int(lengths["cdr1"]),
                "cdr2_length": int(lengths["cdr2"]),
                "cdr3_length": int(lengths["cdr3"]),
            }
