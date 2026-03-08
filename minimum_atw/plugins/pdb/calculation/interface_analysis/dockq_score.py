from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import biotite.structure as struc
import numpy as np
from biotite.structure.io import load_structure

from ....base import Context, InterfacePlugin


# DockQ sigmoid scales from Basu & Wallner (2016) https://doi.org/10.1371/journal.pone.0161879
_LRMS_SCALE = 8.5
_IRMS_SCALE = 1.5

_DEFAULT_CONTACT_DISTANCE = 5.0


@lru_cache(maxsize=8)
def _load_reference(path: str) -> struc.AtomArray:
    return load_structure(Path(path))


def _ca_atoms(arr: struc.AtomArray) -> struc.AtomArray:
    return arr[arr.atom_name == "CA"]


def _select_chains(arr: struc.AtomArray, chain_ids: tuple[str, ...]) -> struc.AtomArray:
    if not chain_ids:
        return arr[:0]
    mask = np.isin(arr.chain_id.astype(str), np.asarray(chain_ids, dtype=object))
    return arr[mask]


def _role_chains(ctx: Context, role: str) -> tuple[str, ...]:
    return tuple(str(c) for c in ctx.role_map.get(role, ()))


def _residue_contact_pairs(
    left: struc.AtomArray,
    right: struc.AtomArray,
    *,
    contact_distance: float,
) -> set[tuple[tuple[str, int], tuple[str, int]]]:
    """Residue-level contact pairs keyed by (chain_id, res_id)."""
    if len(left) == 0 or len(right) == 0:
        return set()
    cl = struc.CellList(right.coord, cell_size=float(contact_distance))
    near = cl.get_atoms(left.coord, contact_distance, as_mask=True)
    if near.size == 0 or not np.any(near):
        return set()
    pairs: set[tuple[tuple[str, int], tuple[str, int]]] = set()
    left_idx, right_idx = np.nonzero(near)
    for li, ri in zip(left_idx.tolist(), right_idx.tolist()):
        pairs.add(
            (
                (str(left.chain_id[li]), int(left.res_id[li])),
                (str(right.chain_id[ri]), int(right.res_id[ri])),
            )
        )
    return pairs


def _matched_ca_coords(
    ref_ca: struc.AtomArray,
    model_ca: struc.AtomArray,
    *,
    residue_keys: set[tuple[str, int]] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Match Cα atoms by (chain_id, res_id).
    If residue_keys given, only include those residues.
    Returns (ref_coords, model_coords) as paired numpy arrays.
    """
    ref_map: dict[tuple[str, int], np.ndarray] = {}
    for i in range(len(ref_ca)):
        key = (str(ref_ca.chain_id[i]), int(ref_ca.res_id[i]))
        if residue_keys is not None and key not in residue_keys:
            continue
        if key not in ref_map:
            ref_map[key] = ref_ca.coord[i].copy()

    ref_coords: list[np.ndarray] = []
    model_coords: list[np.ndarray] = []
    seen: set[tuple[str, int]] = set()
    for i in range(len(model_ca)):
        key = (str(model_ca.chain_id[i]), int(model_ca.res_id[i]))
        if key in ref_map and key not in seen:
            seen.add(key)
            ref_coords.append(ref_map[key])
            model_coords.append(model_ca.coord[i].copy())

    if not ref_coords:
        return np.empty((0, 3)), np.empty((0, 3))
    return np.stack(ref_coords), np.stack(model_coords)


def _rmsd(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) == 0:
        return float("nan")
    diff = a - b
    return float(np.sqrt(np.mean(np.sum(diff**2, axis=1))))


def _superimpose_transform(
    ref_coords: np.ndarray,
    mobile_coords: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute the optimal rotation matrix R and translation t that minimises
    RMSD between ref and mobile (Kabsch algorithm).
    Returns (R, t) such that mobile_aligned = mobile @ R.T + t.
    """
    ref_c = ref_coords - ref_coords.mean(axis=0)
    mob_c = mobile_coords - mobile_coords.mean(axis=0)
    H = mob_c.T @ ref_c
    U, _S, Vt = np.linalg.svd(H)
    det = np.linalg.det(Vt.T @ U.T)
    D = np.diag([1.0, 1.0, float(det)])
    R = (Vt.T @ D @ U.T)
    t = ref_coords.mean(axis=0) - mobile_coords.mean(axis=0) @ R.T
    return R, t


def _apply_transform(coords: np.ndarray, R: np.ndarray, t: np.ndarray) -> np.ndarray:
    return coords @ R.T + t


def compute_dockq(
    ref: struc.AtomArray,
    model_left: struc.AtomArray,
    model_right: struc.AtomArray,
    *,
    left_chains: tuple[str, ...],
    right_chains: tuple[str, ...],
    contact_distance: float,
    receptor_is_left: bool,
) -> dict[str, Any]:
    """
    Compute DockQ for a single interface pair against a reference structure.

    receptor_is_left=True  → left role is the superimpose anchor for LRMS.
    receptor_is_left=False → right role is the superimpose anchor.
    """
    nan_result: dict[str, Any] = {
        "fnat": float("nan"),
        "lrms": float("nan"),
        "irms": float("nan"),
        "dockq": float("nan"),
        "n_ref_contacts": 0,
    }

    if receptor_is_left:
        receptor_chains, ligand_chains = left_chains, right_chains
        model_receptor, model_ligand = model_left, model_right
    else:
        receptor_chains, ligand_chains = right_chains, left_chains
        model_receptor, model_ligand = model_right, model_left

    ref_receptor = _select_chains(ref, receptor_chains)
    ref_ligand = _select_chains(ref, ligand_chains)

    if len(ref_receptor) == 0 or len(ref_ligand) == 0:
        return nan_result

    # ── Fnat ───────────────────────────────────────────────────────────────────
    ref_contacts = _residue_contact_pairs(ref_receptor, ref_ligand, contact_distance=contact_distance)
    n_ref_contacts = len(ref_contacts)

    model_contacts = _residue_contact_pairs(model_receptor, model_ligand, contact_distance=contact_distance)

    if n_ref_contacts == 0:
        fnat = float("nan")
    else:
        fnat = float(len(ref_contacts & model_contacts)) / float(n_ref_contacts)

    # ── LRMS ───────────────────────────────────────────────────────────────────
    # Superimpose model receptor Cα onto ref receptor Cα, then measure
    # RMSD of the (transformed) ligand Cα against the reference ligand Cα.
    ref_rec_ca = _ca_atoms(ref_receptor)
    model_rec_ca = _ca_atoms(model_receptor)
    ref_lig_ca = _ca_atoms(ref_ligand)
    model_lig_ca = _ca_atoms(model_ligand)

    ref_rec_coords, model_rec_coords = _matched_ca_coords(ref_rec_ca, model_rec_ca)

    if len(ref_rec_coords) < 3:
        lrms = float("nan")
    else:
        ref_lig_coords, model_lig_coords = _matched_ca_coords(ref_lig_ca, model_lig_ca)
        if len(ref_lig_coords) == 0:
            lrms = float("nan")
        else:
            R, t = _superimpose_transform(ref_rec_coords, model_rec_coords)
            model_lig_fitted = _apply_transform(model_lig_coords, R, t)
            lrms = _rmsd(ref_lig_coords, model_lig_fitted)

    # ── iRMS ───────────────────────────────────────────────────────────────────
    # Superimpose on interface Cα atoms (both sides), measure interface RMSD.
    if n_ref_contacts == 0:
        irms = float("nan")
    else:
        interface_keys: set[tuple[str, int]] = set()
        for left_key, right_key in ref_contacts:
            interface_keys.add(left_key)
            interface_keys.add(right_key)

        ref_all_ca = _ca_atoms(ref)
        model_all_ca = _ca_atoms(struc.concatenate([model_receptor, model_ligand]))

        ref_if_coords, model_if_coords = _matched_ca_coords(
            ref_all_ca, model_all_ca, residue_keys=interface_keys
        )

        if len(ref_if_coords) < 3:
            irms = float("nan")
        else:
            R_if, t_if = _superimpose_transform(ref_if_coords, model_if_coords)
            model_if_fitted = _apply_transform(model_if_coords, R_if, t_if)
            irms = _rmsd(ref_if_coords, model_if_fitted)

    # ── DockQ ──────────────────────────────────────────────────────────────────
    if any(math.isnan(v) for v in (fnat, lrms, irms)):
        dockq = float("nan")
    else:
        lrms_score = 1.0 / (1.0 + (lrms / _LRMS_SCALE) ** 2)
        irms_score = 1.0 / (1.0 + (irms / _IRMS_SCALE) ** 2)
        dockq = (fnat + lrms_score + irms_score) / 3.0

    return {
        "fnat": fnat,
        "lrms": lrms,
        "irms": irms,
        "dockq": dockq,
        "n_ref_contacts": n_ref_contacts,
    }


class DockQPlugin(InterfacePlugin):
    """
    DockQ interface quality score comparing each model to a reference ('native') structure.

    Requires a reference PDB whose chain IDs match those used in `roles`.
    Configure via plugin_params:

      plugin_params:
        dockq_score:
          reference_path: "/path/to/native_complex.pdb"   # required
          receptor_role: "antigen"    # role to superimpose on for LRMS (default: right role)
          contact_distance: 5.0       # Å cutoff for Fnat contact definition (default: 5.0)

    Output columns (prefix: dockq):
      dockq__dockq            — DockQ score [0,1]
      dockq__fnat             — fraction of native contacts recovered [0,1]
      dockq__lrms             — ligand RMSD after receptor superposition (Å)
      dockq__irms             — interface RMSD after interface superposition (Å)
      dockq__n_ref_contacts   — residue contact count in the reference
      dockq__contact_distance — contact cutoff used for Fnat (Å)

    DockQ quality thresholds:
      < 0.23  Incorrect
      0.23 – 0.49  Acceptable
      0.49 – 0.80  Medium
      ≥ 0.80  High

    Reference: Basu & Wallner (2016), PLOS ONE
               https://doi.org/10.1371/journal.pone.0161879
    """

    name = "dockq_score"
    prefix = "dockq"

    def available(self, ctx: Context | None) -> tuple[bool, str]:
        if ctx is None:
            return True, ""
        params = self.plugin_params(ctx)
        ref_path = params.get("reference_path") or getattr(ctx.config, "dockq_reference_path", None)
        if not ref_path:
            return False, "dockq_score requires plugin_params.dockq_score.reference_path"
        return True, ""

    def run(self, ctx: Context):
        params = self.plugin_params(ctx)
        ref_path = str(
            params.get("reference_path") or getattr(ctx.config, "dockq_reference_path", "")
        )
        if not ref_path:
            return

        contact_distance = float(params.get("contact_distance", _DEFAULT_CONTACT_DISTANCE))
        receptor_role_override: str | None = params.get("receptor_role")

        try:
            ref = _load_reference(ref_path)
        except Exception as exc:
            raise RuntimeError(
                f"dockq_score: failed to load reference {ref_path!r}: {exc}"
            ) from exc

        for left_role, right_role, left, right in self.iter_role_pairs(ctx):
            left_chains = _role_chains(ctx, left_role)
            right_chains = _role_chains(ctx, right_role)

            if receptor_role_override:
                receptor_is_left = str(receptor_role_override) == left_role
            else:
                receptor_is_left = False  # right role is receptor by default

            result = compute_dockq(
                ref,
                left,
                right,
                left_chains=left_chains,
                right_chains=right_chains,
                contact_distance=contact_distance,
                receptor_is_left=receptor_is_left,
            )
            yield {
                **self.pair_identity_row(ctx, left_role=left_role, right_role=right_role),
                "contact_distance": contact_distance,
                **result,
            }
