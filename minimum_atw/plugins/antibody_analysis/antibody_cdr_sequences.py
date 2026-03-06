from __future__ import annotations

from ..base import Context
from .base import AntibodyPluginBase
from .antibody_numbering import imgt_cdr_sequences


class AntibodyCDRSequencesPlugin(AntibodyPluginBase):
    name = "antibody_cdr_sequences"
    prefix = "abseq"

    def run(self, ctx: Context):
        for role_name, chain_ids, sequence in self.iter_antibody_roles(ctx):
            cdrs = imgt_cdr_sequences(sequence)
            yield {
                "__table__": "roles",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "role": role_name,
                "chain_ids": ";".join(chain_ids),
                "sequence_length": int(len(sequence)),
                "cdr1_sequence": str(cdrs["cdr1"]),
                "cdr2_sequence": str(cdrs["cdr2"]),
                "cdr3_sequence": str(cdrs["cdr3"]),
            }
