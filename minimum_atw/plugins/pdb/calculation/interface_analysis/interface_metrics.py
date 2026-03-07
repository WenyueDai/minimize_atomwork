from __future__ import annotations

from typing import Any

import biotite.structure as struc
import numpy as np

from ...annotations import chain_residue_entries, iter_unique_residues, residue_code, residue_infos


AA_CHARGE = {
    "D": -1,
    "E": -1,
    "K": 1,
    "R": 1,
}
AA_HYDROPHOBIC = set("AVILMFWYP")
AA_POLAR = set("STNQCH")
AA_AROMATIC = set("FWYH")


def residue_tokens(residue_entries: list[tuple[str, int, str]]) -> str:
    return ";".join(f"{chain_id}:{res_id}:{res_name}" for chain_id, res_id, res_name in residue_entries)


def format_residue_labels(arr) -> str:
    if arr is None or len(arr) == 0:
        return ""
    labels: list[str] = []
    seen: set[tuple[str, int]] = set()
    for chain_id, res_id in zip(arr.chain_id.astype(str), arr.res_id):
        key = (str(chain_id), int(res_id))
        if key in seen:
            continue
        seen.add(key)
        labels.append(f"{key[0]}:{key[1]}")
    return ";".join(labels)


def residue_charge_from_resname(res_name: str) -> int:
    return int(AA_CHARGE.get(residue_code(res_name), 0))


def summarize_residue_properties(infos: list[dict[str, Any]], side: str) -> dict[str, float | int]:
    aa_infos = [info for info in infos if info.get("aa") and str(info["aa"]) != "X"]
    n = len(aa_infos)
    denom = float(n) if n else 1.0

    def frac(pred) -> float:
        if not n:
            return 0.0
        return float(sum(1 for info in aa_infos if pred(info["aa"])) / denom)

    charge_sum = int(sum(AA_CHARGE.get(str(info["aa"]), 0) for info in aa_infos))
    return {
        f"{side}_n_interface_residues": int(len(infos)),
        f"{side}_interface_charge_sum": charge_sum,
        f"{side}_interface_hydrophobic_fraction": frac(lambda aa: aa in AA_HYDROPHOBIC),
        f"{side}_interface_polar_fraction": frac(lambda aa: aa in AA_POLAR),
        f"{side}_interface_aromatic_fraction": frac(lambda aa: aa in AA_AROMATIC),
        f"{side}_interface_glycine_fraction": frac(lambda aa: aa == "G"),
        f"{side}_interface_proline_fraction": frac(lambda aa: aa == "P"),
    }


def valid_atoms(arr):
    if arr is None or len(arr) == 0:
        return arr[:0]
    return arr[~np.isnan(arr.coord).any(axis=1)]


def _cell_size(cell_size: float | None, contact_cutoff: float) -> float:
    if cell_size is None or float(cell_size) <= 0:
        return float(contact_cutoff)
    return float(cell_size)


def _contact_mask(left, right, *, contact_cutoff: float, cell_size: float | None = None):
    left_atoms = valid_atoms(left)
    right_atoms = valid_atoms(right)
    if len(left_atoms) == 0 or len(right_atoms) == 0:
        return left_atoms, right_atoms, np.empty((0, 0), dtype=bool)
    cl = struc.CellList(right_atoms.coord, cell_size=_cell_size(cell_size, contact_cutoff))
    near = cl.get_atoms(left_atoms.coord, contact_cutoff, as_mask=True)
    return left_atoms, right_atoms, near


def interface_residue_labels(
    left,
    right,
    *,
    contact_cutoff: float,
    cell_size: float | None = None,
):
    if left is None or right is None or len(left) == 0 or len(right) == 0:
        return left[:0], right[:0]

    left_atoms, right_atoms, near = _contact_mask(
        left,
        right,
        contact_cutoff=contact_cutoff,
        cell_size=cell_size,
    )
    if near.size == 0:
        return left_atoms[:0], right_atoms[:0]

    left_contact = left_atoms[np.any(near, axis=1)]
    right_contact = right_atoms[np.any(near, axis=0)]
    return left_contact, right_contact


def interface_residue_contact_pairs(
    left,
    right,
    *,
    contact_cutoff: float,
    cell_size: float | None = None,
) -> tuple[list[tuple[tuple[str, int, str], tuple[str, int, str]]], Any, Any]:
    if left is None or right is None or len(left) == 0 or len(right) == 0:
        return [], left[:0], right[:0]

    left_atoms, right_atoms, near = _contact_mask(
        left,
        right,
        contact_cutoff=contact_cutoff,
        cell_size=cell_size,
    )
    if near.size == 0:
        return [], left_atoms[:0], right_atoms[:0]

    left_contact = left_atoms[np.any(near, axis=1)]
    right_contact = right_atoms[np.any(near, axis=0)]

    pair_set: set[tuple[tuple[str, int, str], tuple[str, int, str]]] = set()
    left_idx, right_idx = np.nonzero(near)
    for li, ri in zip(left_idx.tolist(), right_idx.tolist()):
        left_key = (
            str(left_atoms.chain_id[li]),
            int(left_atoms.res_id[li]),
            residue_code(str(left_atoms.res_name[li])),
        )
        right_key = (
            str(right_atoms.chain_id[ri]),
            int(right_atoms.res_id[ri]),
            residue_code(str(right_atoms.res_name[ri])),
        )
        pair_set.add((left_key, right_key))

    pair_list = sorted(
        pair_set,
        key=lambda pair: (pair[0][0], pair[0][1], pair[1][0], pair[1][1], pair[0][2], pair[1][2]),
    )
    return pair_list, left_contact, right_contact


def residue_contact_pair_tokens(
    pair_list: list[tuple[tuple[str, int, str], tuple[str, int, str]]],
) -> str:
    return ";".join(
        f"{left_chain}:{left_res}:{left_name}|{right_chain}:{right_res}:{right_name}"
        for (left_chain, left_res, left_name), (right_chain, right_res, right_name) in pair_list
    )


def interface_contact_summary(
    left,
    right,
    *,
    contact_distance: float,
    cell_size: float | None = None,
) -> dict[str, Any] | None:
    if len(left) == 0 or len(right) == 0:
        return None

    left_atoms, right_atoms, near = _contact_mask(
        left,
        right,
        contact_cutoff=contact_distance,
        cell_size=cell_size,
    )
    if near.size == 0:
        return None

    left_contact_atoms = left_atoms[np.any(near, axis=1)]
    right_contact_atoms = right_atoms[np.any(near, axis=0)]
    if len(left_contact_atoms) == 0 or len(right_contact_atoms) == 0:
        return None

    pair_set: set[tuple[tuple[str, int, str], tuple[str, int, str]]] = set()
    left_idx, right_idx = np.nonzero(near)
    for li, ri in zip(left_idx.tolist(), right_idx.tolist()):
        pair_set.add(
            (
                (
                    str(left_atoms.chain_id[li]),
                    int(left_atoms.res_id[li]),
                    residue_code(str(left_atoms.res_name[li])),
                ),
                (
                    str(right_atoms.chain_id[ri]),
                    int(right_atoms.res_id[ri]),
                    residue_code(str(right_atoms.res_name[ri])),
                ),
            )
        )
    pair_list = sorted(
        pair_set,
        key=lambda pair: (pair[0][0], pair[0][1], pair[1][0], pair[1][1], pair[0][2], pair[1][2]),
    )
    if not pair_list:
        return None

    left_res = chain_residue_entries(left_contact_atoms)
    right_res = chain_residue_entries(right_contact_atoms)

    return {
        "n_contact_atom_pairs": int(np.count_nonzero(near)),
        "left_contact_atoms": left_contact_atoms,
        "right_contact_atoms": right_contact_atoms,
        "left_interface_residues": left_res,
        "right_interface_residues": right_res,
        "residue_contact_pairs": pair_list,
    }
