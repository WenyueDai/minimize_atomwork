from __future__ import annotations

import numpy as np

from ..antibody_analysis.antibody_numbering import cdr_indices
from ..antibody_analysis.base import (
    antibody_role_sequences,
    cdr_definition_from_config,
    numbering_scheme_from_config,
)
from ..base import Context, InterfacePlugin
from ..sequence import chain_residue_entries


def _residue_tokens(residue_entries: list[tuple[str, int, str]]) -> str:
    return ";".join(f"{chain_id}:{res_id}:{res_name}" for chain_id, res_id, res_name in residue_entries)


def _cdr_interface_fields(
    ctx: Context,
    *,
    side_prefix: str,
    side_arr,
    interface_residues: list[tuple[str, int, str]],
) -> dict[str, object]:
    side_chain_ids = {str(chain_id) for chain_id in side_arr.chain_id.astype(str)}
    interface_keys = {(chain_id, res_id) for chain_id, res_id, _res_name in interface_residues}
    scheme = numbering_scheme_from_config(ctx.config)
    cdr_definition = cdr_definition_from_config(ctx.config)
    fields: dict[str, object] = {}

    for role_name, chain_ids, sequence in antibody_role_sequences(ctx):
        if not set(chain_ids).issubset(side_chain_ids):
            continue
        role_arr = ctx.roles.get(role_name)
        if role_arr is None or len(role_arr) == 0:
            continue
        role_entries = chain_residue_entries(role_arr)
        if len(role_entries) != len(sequence):
            continue

        cdr_map = cdr_indices(sequence, scheme=scheme, cdr_definition=cdr_definition)
        for cdr_name, indices in cdr_map.items():
            index_set = set(indices)
            cdr_interface_residues = [
                entry
                for idx, entry in enumerate(role_entries)
                if idx in index_set and (entry[0], entry[1]) in interface_keys
            ]
            fields[f"n_{side_prefix}_{role_name}_{cdr_name}_interface_residues"] = int(len(cdr_interface_residues))
            fields[f"{side_prefix}_{role_name}_{cdr_name}_interface_residues"] = _residue_tokens(cdr_interface_residues)
    return fields


class InterfaceContactsPlugin(InterfacePlugin):
    name = "interface_contacts"
    prefix = "iface"

    def run(self, ctx: Context):
        cutoff = float(ctx.config.contact_distance)
        for left_role, right_role, left, right in self.iter_role_pairs(ctx):
            if len(left) == 0 or len(right) == 0:
                continue

            left_coords = left.coord
            right_coords = right.coord
            dists = np.linalg.norm(left_coords[:, None, :] - right_coords[None, :, :], axis=2)
            contact_mask = dists <= cutoff
            if not np.any(contact_mask):
                continue

            left_contact_atoms = left[np.any(contact_mask, axis=1)]
            right_contact_atoms = right[np.any(contact_mask, axis=0)]
            left_res = chain_residue_entries(left_contact_atoms)
            right_res = chain_residue_entries(right_contact_atoms)

            yield {
                **self.pair_identity_row(ctx, left_role=left_role, right_role=right_role),
                "contact_distance": cutoff,
                "n_contact_atom_pairs": int(np.count_nonzero(contact_mask)),
                "n_left_contact_atoms": int(len(left_contact_atoms)),
                "n_right_contact_atoms": int(len(right_contact_atoms)),
                "n_left_interface_residues": int(len(left_res)),
                "n_right_interface_residues": int(len(right_res)),
                "left_interface_residues": _residue_tokens(left_res),
                "right_interface_residues": _residue_tokens(right_res),
                **_cdr_interface_fields(ctx, side_prefix="left", side_arr=left, interface_residues=left_res),
                **_cdr_interface_fields(ctx, side_prefix="right", side_arr=right, interface_residues=right_res),
            }
