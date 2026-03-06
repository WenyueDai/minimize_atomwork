from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import biotite.structure as struc
import numpy as np
from biotite.structure.io import load_structure

from .base import BaseManipulation


@lru_cache(maxsize=16)
def _load_reference(path: str) -> struc.AtomArray:
    return load_structure(Path(path))


def _select_chains(arr: struc.AtomArray, chain_ids: tuple[str, ...]) -> struc.AtomArray:
    if not chain_ids:
        return arr
    mask = np.isin(arr.chain_id.astype(str), np.asarray(chain_ids, dtype=object))
    return arr[mask]


def _atom_key(arr: struc.AtomArray, idx: int) -> tuple[str, int, str, str]:
    ins_code = ""
    if hasattr(arr, "ins_code"):
        ins_code = str(arr.ins_code[idx])
    return (
        str(arr.chain_id[idx]),
        int(arr.res_id[idx]),
        ins_code,
        str(arr.atom_name[idx]),
    )


def _matched_atom_indices(fixed: struc.AtomArray, mobile: struc.AtomArray) -> tuple[np.ndarray, np.ndarray]:
    fixed_by_key: dict[tuple[str, int, str, str], int] = {}
    for idx in range(len(fixed)):
        key = _atom_key(fixed, idx)
        if key not in fixed_by_key:
            fixed_by_key[key] = idx

    fixed_idx: list[int] = []
    mobile_idx: list[int] = []
    for idx in range(len(mobile)):
        key = _atom_key(mobile, idx)
        fixed_match = fixed_by_key.get(key)
        if fixed_match is None:
            continue
        fixed_idx.append(fixed_match)
        mobile_idx.append(idx)
    return np.asarray(fixed_idx, dtype=int), np.asarray(mobile_idx, dtype=int)


class SuperimposeHomologyManipulation(BaseManipulation):
    name = "superimpose_homology"
    prefix = "sup"

    def __init__(self) -> None:
        self._reference: struc.AtomArray | None = None
        self._reference_path: str | None = None

    def available(self, ctx) -> tuple[bool, str]:
        # always available; if the user provided a path it will be used,
        # otherwise the first structure encountered during a run becomes the
        # implicit reference.
        return True, ""

    def run(self, ctx):
        if self._reference is None:
            if getattr(ctx.config, "superimpose_reference_path", None):
                self._reference_path = str(Path(ctx.config.superimpose_reference_path).expanduser().resolve())
                self._reference = _load_reference(self._reference_path)
            else:
                self._reference = ctx.aa.copy()
                self._reference_path = ctx.path
                yield {
                    "__table__": "structures",
                    "path": ctx.path,
                    "assembly_id": ctx.assembly_id,
                    "note": "reference_structure",
                }
                return

        fixed = self._reference
        on_chains = tuple(str(chain_id) for chain_id in ctx.config.superimpose_on_chains if str(chain_id))

        mobile = ctx.aa.copy()
        fixed_anchor = _select_chains(fixed, on_chains)
        mobile_anchor = _select_chains(mobile, on_chains)
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
        fixed_idx, mobile_idx = _matched_atom_indices(fixed, fitted_complex)
        if len(fixed_idx) == 0:
            raise ValueError("no_common_atoms_for_rmsd")

        ctx.aa = fitted_complex
        ctx.rebuild_views()

        complex_rmsd = float(struc.rmsd(fixed[fixed_idx], fitted_complex[mobile_idx]))
        yield {
            "__table__": "structures",
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "reference_path": self._reference_path,
            "on_chains": ";".join(on_chains),
            "anchor_atoms_fixed": int(len(fixed_anchor_idx)),
            "anchor_atoms_mobile": int(len(mobile_anchor_idx)),
            "alignment_method": alignment_method,
            "complex_rmsd": complex_rmsd,
            "complex_matched_atoms": int(len(fixed_idx)),
        }

        fixed_chain = fixed.chain_id[fixed_idx].astype(str)
        mobile_chain = fitted_complex.chain_id[mobile_idx].astype(str)
        common_chain_ids = sorted(set(fixed_chain) & set(mobile_chain))
        for chain_id in common_chain_ids:
            chain_mask = (fixed_chain == chain_id) & (mobile_chain == chain_id)
            chain_fixed_idx = fixed_idx[chain_mask]
            chain_mobile_idx = mobile_idx[chain_mask]
            if len(chain_fixed_idx) == 0:
                continue
            chain_rmsd = float(struc.rmsd(fixed[chain_fixed_idx], fitted_complex[chain_mobile_idx]))
            yield {
                "__table__": "chains",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "chain_id": str(chain_id),
                "rmsd": chain_rmsd,
                "matched_atoms": int(len(chain_fixed_idx)),
            }
