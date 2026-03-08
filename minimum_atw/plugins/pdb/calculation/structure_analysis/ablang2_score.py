from __future__ import annotations

import math
from typing import Any

import numpy as np

from ....base import Context, RolePlugin


_MODEL_CACHE: dict[str, Any] = {}

_SINGLE_CHAIN_MODEL = "ablang1-heavy"
_PAIRED_MODEL = "ablang2-paired"


def _get_sequence_for_chain(chain_aa) -> str:
    """Extract 1-letter amino acid sequence from a biotite AtomArray (single chain)."""
    from biotite.sequence import ProteinSequence
    from biotite.structure.residues import get_residues

    _, res_names = get_residues(chain_aa)
    seq = "".join(ProteinSequence.convert_letter_3to1(r) for r in res_names)
    return seq


def _resolve_device(param: str) -> str:
    if param != "auto":
        return param
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _load_model(model_name: str, device: str) -> Any:
    """Load an AbLang2 model, cached by model name and device."""
    key = f"{model_name}_{device}"
    if key not in _MODEL_CACHE:
        import ablang2

        model = ablang2.pretrained(model_name, device=device)
        model.freeze()
        _MODEL_CACHE[key] = model
    return _MODEL_CACHE[key]


def _score_single_chain(model, seq: str, device: str) -> float:
    """Score a single antibody chain with ablang1-heavy. Returns mean log-likelihood."""
    import torch
    import torch.nn.functional as F

    tokenized = model.tokenizer([seq], pad=True, w_extra_tkns=False, device=device)
    with torch.no_grad():
        logits = model.AbLang(tokenized)[0]  # (1, L, vocab)
    log_probs = F.log_softmax(logits, dim=-1)
    token_ids = tokenized["input_ids"][0]
    # Exclude padding tokens (id=0) and special tokens (BOS=1, EOS=2); positions 1..len(seq)
    seq_log_probs = []
    for i in range(1, len(seq) + 1):
        if i < log_probs.shape[1]:
            tok = int(token_ids[i])
            if tok > 2:
                seq_log_probs.append(float(log_probs[0, i, tok]))
    if not seq_log_probs:
        return float("nan")
    return float(np.mean(seq_log_probs))


def _score_paired(model, vh_seq: str, vl_seq: str, device: str) -> tuple[float, float]:
    """Score VH+VL pair with ablang2-paired. Returns (mean_ll_vh, mean_ll_vl)."""
    import torch
    import torch.nn.functional as F

    tokenized = model.tokenizer([(vh_seq, vl_seq)], pad=True, w_extra_tkns=False, device=device)
    with torch.no_grad():
        logits = model.AbLang(tokenized)[0]  # (1, L, vocab)
    log_probs = F.log_softmax(logits, dim=-1)
    token_ids = tokenized["input_ids"][0]
    # Collect log-probs for non-special tokens (skip BOS/EOS/pad, id<=2)
    seq_log_probs = []
    for i in range(1, log_probs.shape[1] - 1):
        tok = int(token_ids[i])
        if tok > 2:
            seq_log_probs.append(float(log_probs[0, i, tok]))
    if not seq_log_probs:
        return float("nan"), float("nan")
    # Approximate split by chain lengths (paired tokeniser inserts a separator token)
    vh_len = len(vh_seq)
    vl_len = len(vl_seq)
    total = vh_len + vl_len
    if len(seq_log_probs) >= total:
        vh_ll = float(np.mean(seq_log_probs[:vh_len])) if vh_len > 0 else float("nan")
        vl_ll = float(np.mean(seq_log_probs[vh_len:vh_len + vl_len])) if vl_len > 0 else float("nan")
    else:
        mean_ll = float(np.mean(seq_log_probs))
        vh_ll = mean_ll
        vl_ll = mean_ll
    return vh_ll, vl_ll


class AbLang2ScorePlugin(RolePlugin):
    """
    AbLang2 antibody language model log-likelihood score per role.

    Scores antibody sequences using AbLang2 (paired VH+VL) or AbLang1 (single chain).
    The model is selected automatically based on whether the role has one or two chains:
      - 2-chain roles (e.g. antibody = VH + VL): uses ablang2-paired
      - 1-chain roles (e.g. vhh): uses ablang1-heavy

    Higher log-likelihood indicates a sequence more consistent with the antibody repertoire.
    Useful for ranking AF2 antibody models by sequence naturalness.

    Requires: pip install minimum-atomworks[ablang2]

    Configure via plugin_params:
      plugin_params:
        ablang2_score:
          device: auto    # auto | cpu | cuda (default: auto)

    Output columns (prefix: ablang2):
      ablang2__ll_mean       — mean log-likelihood over all residues in the role
      ablang2__ll_chain_0    — mean LL for first chain (VH in paired mode)
      ablang2__ll_chain_1    — mean LL for second chain (VL in paired mode; nan if single-chain)
      ablang2__n_residues    — total residues scored
      ablang2__n_chains      — number of chains in the role
      ablang2__model         — model name used (ablang2-paired or ablang1-heavy)

    Reference: Martinkus et al. (2024), Antibody Engineering & Therapeutics
               https://doi.org/10.1101/2023.01.08.523187
    """

    name = "ablang2_score"
    prefix = "ablang2"

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
        if ctx is None:
            return True, ""
        try:
            import ablang2  # noqa: F401
        except ImportError:
            return False, "ablang2_score requires ablang2 (pip install minimum-atomworks[ablang2])"
        return True, ""

    def run(self, ctx: Context):
        params = self.plugin_params(ctx)
        device = _resolve_device(str(params.get("device", "auto")))

        for role_name, _role_aa in self.iter_roles(ctx):
            chain_ids = [str(c) for c in (ctx.role_map.get(role_name) or ())]
            if not chain_ids:
                continue

            # Extract sequences for each chain in the role
            seqs: dict[str, str] = {}
            for chain_id in chain_ids:
                chain_arr = ctx.chains.get(chain_id)
                if chain_arr is None or len(chain_arr) == 0:
                    continue
                try:
                    seq = _get_sequence_for_chain(chain_arr)
                    if seq:
                        seqs[chain_id] = seq
                except Exception:
                    pass

            if not seqs:
                continue

            n_chains = len(seqs)
            chain_list = list(seqs.keys())

            try:
                if n_chains >= 2:
                    model_name = _PAIRED_MODEL
                    model = _load_model(model_name, device)
                    vh_seq = seqs[chain_list[0]]
                    vl_seq = seqs[chain_list[1]]
                    ll_0, ll_1 = _score_paired(model, vh_seq, vl_seq, device)
                    n_residues = len(vh_seq) + len(vl_seq)
                    valid = [v for v in [ll_0, ll_1] if not math.isnan(v)]
                    ll_mean = float(np.mean(valid)) if valid else float("nan")
                else:
                    model_name = _SINGLE_CHAIN_MODEL
                    model = _load_model(model_name, device)
                    seq = seqs[chain_list[0]]
                    ll_0 = _score_single_chain(model, seq, device)
                    ll_1 = float("nan")
                    n_residues = len(seq)
                    ll_mean = ll_0
            except Exception:
                continue

            yield {
                "grain": "role",
                **self.role_identity_row(ctx, role_name=role_name),
                "n_chains": n_chains,
                "n_residues": n_residues,
                "model": model_name,
                "ll_mean": ll_mean,
                "ll_chain_0": ll_0,
                "ll_chain_1": ll_1,
            }
