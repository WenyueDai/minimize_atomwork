from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import biotite.structure as struc
import numpy as np
from biotite.structure.io import load_structure


@lru_cache(maxsize=16)
def load_reference_structure(path: str) -> struc.AtomArray:
    return load_structure(Path(path))


def select_chains(arr: struc.AtomArray, chain_ids: tuple[str, ...]) -> struc.AtomArray:
    if not chain_ids:
        return arr
    mask = np.isin(arr.chain_id.astype(str), np.asarray(chain_ids, dtype=object))
    return arr[mask]


def atom_key(arr: struc.AtomArray, idx: int) -> tuple[str, int, str, str]:
    ins_code = ""
    if hasattr(arr, "ins_code"):
        ins_code = str(arr.ins_code[idx])
    return (
        str(arr.chain_id[idx]),
        int(arr.res_id[idx]),
        ins_code,
        str(arr.atom_name[idx]),
    )


def matched_atom_indices(fixed: struc.AtomArray, mobile: struc.AtomArray) -> tuple[np.ndarray, np.ndarray]:
    fixed_by_key: dict[tuple[str, int, str, str], int] = {}
    for idx in range(len(fixed)):
        key = atom_key(fixed, idx)
        if key not in fixed_by_key:
            fixed_by_key[key] = idx

    fixed_idx: list[int] = []
    mobile_idx: list[int] = []
    for idx in range(len(mobile)):
        key = atom_key(mobile, idx)
        fixed_match = fixed_by_key.get(key)
        if fixed_match is None:
            continue
        fixed_idx.append(fixed_match)
        mobile_idx.append(idx)
    return np.asarray(fixed_idx, dtype=int), np.asarray(mobile_idx, dtype=int)


@dataclass(frozen=True)
class SuperimposeResult:
    fitted_complex: struc.AtomArray
    alignment_method: str
    fixed_anchor_idx: np.ndarray
    mobile_anchor_idx: np.ndarray
    fixed_idx: np.ndarray
    mobile_idx: np.ndarray


def superimpose_complex(
    *,
    reference: struc.AtomArray,
    mobile: struc.AtomArray,
    on_chains: tuple[str, ...],
) -> SuperimposeResult:
    fixed_anchor = select_chains(reference, on_chains)
    mobile_anchor = select_chains(mobile, on_chains)
    if len(fixed_anchor) == 0 or len(mobile_anchor) == 0:
        raise ValueError("superimpose anchor selection is empty")

    alignment_method = "homologs"
    try:
        _fitted_anchor, transform, fixed_anchor_idx, mobile_anchor_idx = struc.superimpose_homologs(
            fixed_anchor,
            mobile_anchor,
        )
    except Exception:
        alignment_method = "structural_homologs"
        _fitted_anchor, transform, fixed_anchor_idx, mobile_anchor_idx = struc.superimpose_structural_homologs(
            fixed_anchor,
            mobile_anchor,
        )

    fitted_complex = transform.apply(mobile)
    fixed_idx, mobile_idx = matched_atom_indices(reference, fitted_complex)
    if len(fixed_idx) == 0:
        raise ValueError("no_common_atoms_for_rmsd")

    return SuperimposeResult(
        fitted_complex=fitted_complex,
        alignment_method=alignment_method,
        fixed_anchor_idx=fixed_anchor_idx,
        mobile_anchor_idx=mobile_anchor_idx,
        fixed_idx=fixed_idx,
        mobile_idx=mobile_idx,
    )
