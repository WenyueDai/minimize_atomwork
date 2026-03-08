from __future__ import annotations

import math

import biotite.structure as struc
import numpy as np

from ....base import Context, InterfacePlugin


# Sigmoid constants from Bryant et al. (2022) https://doi.org/10.1038/s41467-022-28865-w
_L = 0.724
_X0 = 152.611
_K = 0.052
_B = 0.018

_DEFAULT_CONTACT_DISTANCE = 8.0


def _cb_ca_atoms(arr):
    """Select CB atoms, falling back to CA for glycine."""
    if arr is None or len(arr) == 0:
        return arr
    mask = (arr.atom_name == "CB") | ((arr.atom_name == "CA") & (arr.res_name == "GLY"))
    return arr[mask]


def _residue_mean_bfactor(arr) -> dict[tuple[str, int], float]:
    """Mean B-factor per residue, keyed by (chain_id, res_id)."""
    buckets: dict[tuple[str, int], list[float]] = {}
    for chain_id, res_id, b in zip(
        arr.chain_id.astype(str), arr.res_id.astype(int), arr.b_factor.astype(float)
    ):
        key = (chain_id, int(res_id))
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(float(b))
    return {k: float(np.mean(v)) for k, v in buckets.items()}


def compute_pdockq(left, right, *, contact_distance: float) -> dict:
    """
    Compute pDockQ for an interface pair.

    Algorithm:
      1. Identify CB atoms (CA for Gly) on each side.
      2. Find cross-chain contacts within *contact_distance* Å.
      3. Average B-factor (pLDDT in AF2 outputs) over contact residues.
      4. pDockQ = L / (1 + exp(-k*(avg_plddt * log10(n_contacts+1) - x0))) + b

    Returns a dict with keys: n_contacts, avg_interface_plddt, pdockq.
    All values are NaN if no contacts are found.
    """
    left_cb = _cb_ca_atoms(left)
    right_cb = _cb_ca_atoms(right)

    if len(left_cb) == 0 or len(right_cb) == 0:
        return {"n_contacts": 0, "avg_interface_plddt": float("nan"), "pdockq": float("nan")}

    cl = struc.CellList(right_cb.coord, cell_size=float(contact_distance))
    near = cl.get_atoms(left_cb.coord, contact_distance, as_mask=True)  # (n_left, n_right)

    if near.size == 0 or not np.any(near):
        return {"n_contacts": 0, "avg_interface_plddt": float("nan"), "pdockq": float("nan")}

    left_idx, right_idx = np.nonzero(near)

    left_keys: set[tuple[str, int]] = set()
    right_keys: set[tuple[str, int]] = set()
    for li in left_idx.tolist():
        left_keys.add((str(left_cb.chain_id[li]), int(left_cb.res_id[li])))
    for ri in right_idx.tolist():
        right_keys.add((str(right_cb.chain_id[ri]), int(right_cb.res_id[ri])))

    # n_contacts = total unique contact residues on both sides (matches original paper)
    n_contacts = len(left_keys) + len(right_keys)

    left_bf = _residue_mean_bfactor(left_cb)
    right_bf = _residue_mean_bfactor(right_cb)
    plddt_vals = [left_bf[k] for k in left_keys if k in left_bf] + [
        right_bf[k] for k in right_keys if k in right_bf
    ]
    valid = [v for v in plddt_vals if not math.isnan(v)]
    avg_plddt = float(np.mean(valid)) if valid else float("nan")

    if math.isnan(avg_plddt):
        return {"n_contacts": n_contacts, "avg_interface_plddt": avg_plddt, "pdockq": float("nan")}

    x = avg_plddt * math.log10(n_contacts + 1)
    pdockq = _L / (1.0 + math.exp(-_K * (x - _X0))) + _B

    return {
        "n_contacts": n_contacts,
        "avg_interface_plddt": avg_plddt,
        "pdockq": pdockq,
    }


class PdockQPlugin(InterfacePlugin):
    """
    pDockQ interface quality score for AlphaFold-Multimer outputs.

    Reads pLDDT from the B-factor column (standard in AF2 PDB files).
    Uses CB atoms (CA for Gly) with an 8 Å contact threshold by default.

    Configurable via plugin_params or a top-level key:
      plugin_params:
        pdockq_score:
          contact_distance: 8.0   # CB-CB cutoff in Angstrom

    Output columns (prefix: pdockq):
      pdockq__pdockq              — pDockQ score [0, 1]; > 0.23 indicates a reliable interface
      pdockq__n_contacts          — number of unique contact residues (left + right combined)
      pdockq__avg_interface_plddt — mean pLDDT over contact residues (from B-factor)
      pdockq__contact_distance    — CB-CB cutoff used (Å)

    Reference: Bryant et al. (2022), Nature Communications
               https://doi.org/10.1038/s41467-022-28865-w
    """

    name = "pdockq_score"
    prefix = "pdockq"

    def run(self, ctx: Context):
        params = self.plugin_params(ctx)
        contact_distance = float(
            params.get(
                "contact_distance",
                getattr(ctx.config, "pdockq_contact_distance", _DEFAULT_CONTACT_DISTANCE),
            )
        )
        for left_role, right_role, left, right in self.iter_role_pairs(ctx):
            result = compute_pdockq(left, right, contact_distance=contact_distance)
            yield {
                **self.pair_identity_row(ctx, left_role=left_role, right_role=right_role),
                "contact_distance": contact_distance,
                **result,
            }
