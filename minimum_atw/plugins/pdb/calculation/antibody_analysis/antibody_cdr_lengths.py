from __future__ import annotations

from ..base import Context
from .base import AntibodyPluginBase
from .antibody_numbering import cdr_lengths


class AntibodyCDRLengthsPlugin(AntibodyPluginBase):
    name = "antibody_cdr_lengths"
    prefix = "abcdr"

    def run(self, ctx: Context):
        scheme = self.numbering_scheme(ctx)
        cdr_definition = self.cdr_definition(ctx)
        for role_name, chain_ids, sequence in self.iter_antibody_roles(ctx):
            lengths = cdr_lengths(sequence, scheme=scheme, cdr_definition=cdr_definition)
            yield {
                "grain": "role",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "role": role_name,
                "chain_ids": ";".join(chain_ids),
                "numbering_scheme": scheme,
                "cdr_definition": cdr_definition or scheme,
                "sequence_length": int(len(sequence)),
                "cdr1_length": int(lengths["cdr1"]),
                "cdr2_length": int(lengths["cdr2"]),
                "cdr3_length": int(lengths["cdr3"]),
            }
