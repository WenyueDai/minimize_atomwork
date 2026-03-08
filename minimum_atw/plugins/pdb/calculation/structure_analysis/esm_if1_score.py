from __future__ import annotations

from typing import Any

import biotite.structure as struc
import numpy as np

from ....base import Context, RolePlugin


_MODEL_CACHE: dict[str, tuple[Any, Any]] = {}

_PADDING_LENGTH = 10


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


def _concatenate_coords(
    coords: dict[str, np.ndarray],
    target_chain_id: str,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Concatenate backbone coords of all chains, target chain first.

    Non-target chains are separated by NaN-padding rows so the model sees
    structural chain boundaries. Returns the full coordinate array and a
    per-position array of chain labels (used to index target positions for LL).
    """
    pad = np.full((_PADDING_LENGTH, 3, 3), np.nan, dtype=np.float32)
    order = [target_chain_id] + [c for c in coords if c != target_chain_id]
    coords_list: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    for i, chain_id in enumerate(order):
        if i > 0:
            coords_list.append(pad)
            labels.append(np.full(_PADDING_LENGTH, "pad"))
        coords_list.append(coords[chain_id].astype(np.float32))
        labels.append(np.full(coords[chain_id].shape[0], chain_id))
    return np.concatenate(coords_list, axis=0), np.concatenate(labels)


def _concatenate_seqs(
    native_seqs: dict[str, str],
    target_seq: str,
    target_chain_id: str,
) -> str:
    """
    Build a concatenated sequence string for the full complex.

    Target chain uses the scoring sequence. Non-target chains use their
    native sequences so the model conditions on actual residue context.
    Chain boundaries are marked with '<cath>' padding tokens (one per
    padding row), matching structural-evolution's convention.
    """
    order = [target_chain_id] + [c for c in native_seqs if c != target_chain_id]
    parts: list[list[str]] = []
    for i, chain_id in enumerate(order):
        if i > 0:
            parts.append(["<mask>"] * (_PADDING_LENGTH - 1) + ["<cath>"])
        if chain_id == target_chain_id:
            parts.append(list(target_seq))
        else:
            parts.append(list(native_seqs[chain_id]))
    return "".join(np.concatenate(parts))


def _score_chain_in_complex(
    model: Any,
    alphabet: Any,
    coords: dict[str, np.ndarray],
    native_seqs: dict[str, str],
    target_chain_id: str,
    target_seq: str,
    device: str,
) -> float:
    """
    ESM-IF1 log-likelihood for target_seq conditioned on the full complex backbone.

    Uses structural-evolution's multi-chain scoring approach:
    - All chain backbones concatenated (target first, NaN-padded separators)
    - All native sequences present; target positions use target_seq
    - Returns mean LL over target chain residues only (not the full complex)

    Device-aware: tensors are moved to the model's device before forward pass,
    avoiding the CPU/GPU mismatch in ESM's built-in get_sequence_loss.
    """
    import torch
    import torch.nn.functional as F
    from esm.inverse_folding.util import CoordBatchConverter

    all_coords, coords_chains = _concatenate_coords(coords, target_chain_id)
    all_seqs = _concatenate_seqs(native_seqs, target_seq, target_chain_id)

    batch_converter = CoordBatchConverter(alphabet)
    coords_t, confidence_t, _, tokens_t, padding_mask_t = batch_converter(
        [(all_coords, None, all_seqs)], device=torch.device(device)
    )

    prev_output_tokens = tokens_t[:, :-1]
    target_t = tokens_t[:, 1:]
    with torch.no_grad():
        logits, _ = model.forward(coords_t, padding_mask_t, confidence_t, prev_output_tokens)
    loss = F.cross_entropy(logits, target_t, reduction="none")
    loss_np = loss[0].cpu().numpy()

    # Index using coords_chains which is 1 shorter than tokens (no BOS shift needed
    # because CoordBatchConverter prepends a BOS token; loss[i] corresponds to
    # predicting token at position i+1, which aligns with coords_chains[i]).
    target_mask = coords_chains == target_chain_id
    n_target = int(target_mask.sum())
    if n_target == 0:
        return float("nan")
    return float(-np.mean(loss_np[:len(coords_chains)][target_mask]))


class EsmIf1ScorePlugin(RolePlugin):
    """
    ESM-IF1 inverse folding log-likelihood for each role's chains in complex context.

    Scores how well each chain's sequence fits its structure using the ESM-IF1
    (GVP-Transformer) inverse folding model. Scoring follows the structural-evolution
    multi-chain approach (Hie et al., 2022): all chain backbones are concatenated as
    structural context (target first, NaN-padded boundaries), all native sequences
    are provided, and the log-likelihood is extracted for the target chain only.

    This gives a cleaner chain-specific LL than ESM's built-in score_sequence_in_complex,
    which scores only the target chain sequence against the full complex backbone.

    Higher log-likelihood indicates better sequence-structure agreement.
    Useful as a confidence signal for AF2 model ranking alongside pLDDT.

    Requires torch and fair-esm:
      pip install torch fair-esm

    Configure via plugin_params:
      plugin_params:
        esm_if1_score:
          device: auto    # auto | cpu | cuda (default: auto)
          on_roles: []    # restrict scoring to specific roles, e.g. ["vh", "vl"]
                          # default [] scores all roles

    Output columns (prefix: esmif1):
      esmif1__ll_fullseq    — mean log-likelihood over the role's chains (target-only)
      esmif1__n_residues    — total residues scored
      esmif1__n_chains      — number of chains in the role

    Reference: Hsu et al. (2022), Science, https://doi.org/10.1126/science.add2187
               Hie et al. (2022), Science, https://doi.org/10.1126/science.abn2100
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
        on_roles: list[str] = list(params.get("on_roles") or [])

        model, alphabet = _load_model(device)

        _patch_biotite()
        from esm.inverse_folding.multichain_util import extract_coords_from_complex

        coords_dict, native_seqs_dict = extract_coords_from_complex(ctx.aa)

        for role_name, _role_aa in self.iter_roles(ctx):
            if on_roles and role_name not in on_roles:
                continue

            chain_ids = [
                str(c)
                for c in (ctx.role_map.get(role_name) or ())
                if str(c) in coords_dict
            ]
            if not chain_ids:
                continue

            ll_vals: list[float] = []
            n_residues = 0

            for chain_id in chain_ids:
                target_seq = str(native_seqs_dict.get(chain_id, ""))
                if not target_seq:
                    continue
                ll = _score_chain_in_complex(
                    model, alphabet, coords_dict, native_seqs_dict,
                    chain_id, target_seq, device,
                )
                ll_vals.append(ll)
                n_residues += len(target_seq)

            if not ll_vals:
                continue

            yield {
                "grain": "role",
                **self.role_identity_row(ctx, role_name=role_name),
                "n_chains": len(chain_ids),
                "n_residues": n_residues,
                "ll_fullseq": float(np.nanmean(ll_vals)),
            }
