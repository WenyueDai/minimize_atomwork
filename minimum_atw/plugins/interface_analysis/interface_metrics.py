from __future__ import annotations

from typing import Any

import numpy as np
from biotite.sequence import ProteinSequence


def residue_code(res_name: str) -> str:
    try:
        return ProteinSequence.convert_letter_3to1(str(res_name))
    except Exception:
        return "X"


def chain_residue_entries(chain_arr) -> list[tuple[str, int, str]]:
    seen: set[tuple[str, int]] = set()
    entries: list[tuple[str, int, str]] = []
    chain_ids = chain_arr.chain_id.astype(str)
    for chain_id, res_id, res_name in zip(chain_ids, chain_arr.res_id, chain_arr.res_name.astype(str)):
        key = (chain_id, int(res_id))
        if key in seen:
            continue
        seen.add(key)
        entries.append((str(chain_id), int(res_id), residue_code(str(res_name))))
    return entries


def residue_tokens(residue_entries: list[tuple[str, int, str]]) -> str:
    return ";".join(f"{chain_id}:{res_id}:{res_name}" for chain_id, res_id, res_name in residue_entries)


def interface_contact_summary(
    left,
    right,
    *,
    contact_distance: float,
) -> dict[str, Any] | None:
    if len(left) == 0 or len(right) == 0:
        return None

    dists = np.linalg.norm(left.coord[:, None, :] - right.coord[None, :, :], axis=2)
    contact_mask = dists <= contact_distance
    if not np.any(contact_mask):
        return None

    left_contact_atoms = left[np.any(contact_mask, axis=1)]
    right_contact_atoms = right[np.any(contact_mask, axis=0)]
    left_res = chain_residue_entries(left_contact_atoms)
    right_res = chain_residue_entries(right_contact_atoms)

    return {
        "n_contact_atom_pairs": int(np.count_nonzero(contact_mask)),
        "left_contact_atoms": left_contact_atoms,
        "right_contact_atoms": right_contact_atoms,
        "left_interface_residues": left_res,
        "right_interface_residues": right_res,
    }
