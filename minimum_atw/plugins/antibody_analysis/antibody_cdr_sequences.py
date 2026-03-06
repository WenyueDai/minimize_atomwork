from __future__ import annotations

from ..base import Context
from .base import AntibodyPluginBase
from .antibody_numbering import cdr_sequences


class AntibodyCDRSequencesPlugin(AntibodyPluginBase):
    name = "antibody_cdr_sequences"
    prefix = "abseq"

    def run(self, ctx: Context):
        scheme = self.numbering_scheme(ctx)
        cdr_definition = self.cdr_definition(ctx)
        for role_name, chain_ids, sequence in self.iter_antibody_roles(ctx):
            cdrs = cdr_sequences(sequence, scheme=scheme, cdr_definition=cdr_definition)
            yield {
                "__table__": "roles",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "role": role_name,
                "chain_ids": ";".join(chain_ids),
                "numbering_scheme": scheme,
                "cdr_definition": cdr_definition or scheme,
                "sequence_length": int(len(sequence)),
                "cdr1_sequence": str(cdrs["cdr1"]),
                "cdr2_sequence": str(cdrs["cdr2"]),
                "cdr3_sequence": str(cdrs["cdr3"]),
            }
