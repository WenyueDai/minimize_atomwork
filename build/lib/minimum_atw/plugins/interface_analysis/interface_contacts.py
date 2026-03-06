from __future__ import annotations

import json

import numpy as np

from ..base import Context, InterfacePlugin


def _residue_keys(arr) -> list[tuple[str, int]]:
    seen = set()
    out = []
    for chain_id, res_id in zip(arr.chain_id.astype(str), arr.res_id):
        key = (chain_id, int(res_id))
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _ca_or_first_coord(arr, chain_id: str, res_id: int) -> tuple[float, float, float]:
    res_atoms = arr[(arr.chain_id.astype(str) == chain_id) & (arr.res_id == res_id)]
    if len(res_atoms) == 0:
        return 0.0, 0.0, 0.0
    ca = res_atoms[res_atoms.atom_name.astype(str) == "CA"]
    atom = ca[0] if len(ca) else res_atoms[0]
    return float(atom.coord[0]), float(atom.coord[1]), float(atom.coord[2])


def _payload_tokens(arr, residue_keys: list[tuple[str, int]]) -> str:
    tokens = []
    for chain_id, res_id in residue_keys:
        x, y, z = _ca_or_first_coord(arr, chain_id, res_id)
        tokens.append(f"{chain_id}:{res_id}:X:{x:.3f},{y:.3f},{z:.3f}")
    return ";".join(tokens)


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
            left_res = _residue_keys(left_contact_atoms)
            right_res = _residue_keys(right_contact_atoms)

            payload = {
                "left_interface_residues": _payload_tokens(left, left_res),
                "right_interface_residues": _payload_tokens(right, right_res),
                "left_n_interface_ca": len(left_res),
                "right_n_interface_ca": len(right_res),
            }

            yield {
                **self.pair_identity_row(ctx, left_role=left_role, right_role=right_role),
                "contact_distance": cutoff,
                "n_contact_atom_pairs": int(np.count_nonzero(contact_mask)),
                "n_left_contact_atoms": int(len(left_contact_atoms)),
                "n_right_contact_atoms": int(len(right_contact_atoms)),
                "n_left_interface_residues": int(len(left_res)),
                "n_right_interface_residues": int(len(right_res)),
                "interface_payload": json.dumps(payload, separators=(",", ":")),
            }
