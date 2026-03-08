from __future__ import annotations

from typing import Any

import biotite.structure as struc
import numpy as np

from ....base import Context, RolePlugin


_MODEL_CACHE: dict[str, tuple[Any, Any]] = {}


def _patch_biotite() -> None:
    """Add filter_backbone alias required by ESM with biotite >= 1.0."""
    if not hasattr(struc, "filter_backbone"):
        struc.filter_backbone = struc.filter_peptide_backbone  # type: ignore[attr-defined]


def _resolve_device(param: str) -> str:
    if param != "auto":
        return param
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _load_model(device: str) -> tuple[Any, Any]:
    """Load ESM-IF1 model and alphabet, cached by device."""
    if device not in _MODEL_CACHE:
        _patch_biotite()
        import esm

        model, alphabet = esm.pretrained.esm_if1_gvp4_t16_142M_UR50()
        model = model.eval()
        if device != "cpu":
            import torch

            model = model.to(torch.device(device))
        _MODEL_CACHE[device] = (model, alphabet)
    return _MODEL_CACHE[device]


class EsmIf1ScorePlugin(RolePlugin):
    """
    ESM-IF1 inverse folding log-likelihood for each role's chains in complex context.

    Scores how well each chain's sequence fits its structure using the ESM-IF1
    (GVP-Transformer) inverse folding model. Each chain is scored in the context
    of the full complex (all chains present in the structure), which means the
    encoder sees surrounding chain coordinates as structural context.

    Higher log-likelihood indicates better sequence-structure agreement.
    Useful as an additional confidence signal for AF2 model ranking alongside pLDDT.

    Requires torch and fair-esm:
      pip install torch fair-esm

    Configure via plugin_params:
      plugin_params:
        esm_if1_score:
          device: auto    # auto | cpu | cuda (default: auto)

    Output columns (prefix: esmif1):
      esmif1__ll_fullseq    — mean log-likelihood over all residues in the role's chains
      esmif1__ll_withcoord  — mean LL excluding residues without backbone coordinates
      esmif1__n_residues    — total residues scored
      esmif1__n_chains      — number of chains in the role

    When a role has multiple chains (e.g. VH+VL), ll values are averaged across chains.

    Reference: Hsu et al. (2022), Science
               https://doi.org/10.1126/science.add2187
    """

    name = "esm_if1_score"
    prefix = "esmif1"

    def scheduling(self, cfg: Any | None = None) -> dict[str, Any]:
        scheduling = super().scheduling(cfg)
        params = dict(getattr(cfg, "plugin_params", {}).get(self.name, {})) if cfg is not None else {}
        device = str(params.get("device", "auto") or "auto").strip().lower()
        gpu_budget = 0
        if cfg is not None:
            gpu_budget = max(int(getattr(cfg, "gpu_workers", 0)), len(getattr(cfg, "gpu_devices", []) or []))
        use_gpu_pool = device.startswith("cuda") or (device == "auto" and gpu_budget > 0)
        scheduling["device_kind"] = "cuda" if use_gpu_pool else (device or "auto")
        scheduling["worker_pool"] = "gpu" if use_gpu_pool else "cpu"
        return scheduling

    def available(self, ctx: Context | None) -> tuple[bool, str]:
        try:
            import torch  # noqa: F401
        except ImportError:
            return False, "esm_if1_score requires torch (pip install torch)"
        try:
            _patch_biotite()
            import esm  # noqa: F401
        except ImportError:
            return False, "esm_if1_score requires fair-esm (pip install fair-esm)"
        return True, ""

    def run(self, ctx: Context):
        params = self.plugin_params(ctx)
        device = _resolve_device(str(params.get("device", "auto")))

        model, alphabet = _load_model(device)

        _patch_biotite()
        from esm.inverse_folding.multichain_util import (
            extract_coords_from_complex,
            score_sequence_in_complex,
        )

        coords_dict, seqs_dict = extract_coords_from_complex(ctx.aa)

        for role_name, _role_aa in self.iter_roles(ctx):
            chain_ids = [
                str(c)
                for c in (ctx.role_map.get(role_name) or ())
                if str(c) in coords_dict
            ]
            if not chain_ids:
                continue

            ll_full_vals: list[float] = []
            ll_coord_vals: list[float] = []
            n_residues = 0

            for chain_id in chain_ids:
                target_seq = seqs_dict.get(chain_id, "")
                if not target_seq:
                    continue
                try:
                    ll_full, ll_coord = score_sequence_in_complex(
                        model, alphabet, coords_dict, chain_id, target_seq
                    )
                    ll_full_vals.append(float(ll_full))
                    ll_coord_vals.append(float(ll_coord))
                    n_residues += len(target_seq)
                except Exception:
                    pass

            if not ll_full_vals:
                continue

            yield {
                "grain": "role",
                **self.role_identity_row(ctx, role_name=role_name),
                "n_chains": len(chain_ids),
                "n_residues": n_residues,
                "ll_fullseq": float(np.mean(ll_full_vals)),
                "ll_withcoord": float(np.mean(ll_coord_vals)),
            }
