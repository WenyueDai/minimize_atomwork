from __future__ import annotations

from typing import Any

from ....base import Context, RolePlugin


_MODEL_CACHE: dict[str, Any] = {}


def _resolve_device(param: str) -> str:
    if param != "auto":
        return param
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _load_model(device: str) -> Any:
    """Load ablang2-paired model, cached by device string."""
    if device not in _MODEL_CACHE:
        import ablang2

        model = ablang2.pretrained("ablang2-paired", device=device)
        model.freeze()
        _MODEL_CACHE[device] = model
    return _MODEL_CACHE[device]


def _get_sequence(arr) -> str:
    from biotite.sequence import ProteinSequence
    from biotite.structure.residues import get_residues

    _, res_names = get_residues(arr)
    return "".join(ProteinSequence.convert_letter_3to1(r) for r in res_names)


def _score_role(model, seqs: list[str], device: str) -> tuple[float, float | None]:
    """
    Score one antibody role using ablang2-paired.

    For single-chain roles (VHH, lone VH/VL), passes an empty string for the
    missing partner chain — ablang2-paired handles this gracefully.

    Returns (ll_chain_0, ll_chain_1 or None if single-chain).
    """
    if len(seqs) >= 2:
        entry = [seqs[0], seqs[1]]
        paired = True
    else:
        entry = [seqs[0], ""]
        paired = False

    ll = model.pseudo_log_likelihood([entry], batch_size=1, align=False)[0]
    ll = float(ll)
    return (ll, ll if paired else None)


class AbLang2ScorePlugin(RolePlugin):
    """
    AbLang2 antibody language model pseudo-log-likelihood score per role.

    Scores antibody sequences using the ablang2-paired model. Works for both
    VH+VL paired roles and single-chain roles (VHH, lone VH/VL):
      - 2-chain roles (e.g. antibody = VH + VL): scored as a VH|VL pair
      - 1-chain roles (e.g. vhh, vh, vl): scored with an empty partner chain

    Higher pseudo-log-likelihood indicates a sequence more consistent with the
    antibody repertoire. Useful for ranking AF2/RF3 antibody models by sequence
    naturalness.

    Requires: pip install minimum-atomworks[ablang2]

    Configure via plugin_params:
      plugin_params:
        ablang2_score:
          device: auto    # auto | cpu | cuda (default: auto)

    Output columns (prefix: ablang2):
      ablang2__ll           — pseudo-log-likelihood for the role
      ablang2__n_residues   — total residues in the role's chains scored
      ablang2__n_chains     — number of chains in the role

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
        try:
            import ablang2  # noqa: F401
        except ImportError:
            return False, "ablang2_score requires ablang2 (pip install minimum-atomworks[ablang2])"
        return True, ""

    def run(self, ctx: Context):
        params = self.plugin_params(ctx)
        device = _resolve_device(str(params.get("device", "auto")))

        model = _load_model(device)

        for role_name, _role_aa in self.iter_roles(ctx):
            chain_ids = [str(c) for c in (ctx.role_map.get(role_name) or ())]
            if not chain_ids:
                continue

            seqs: list[str] = []
            for chain_id in chain_ids:
                chain_arr = ctx.chains.get(chain_id)
                if chain_arr is None or len(chain_arr) == 0:
                    continue
                try:
                    seq = _get_sequence(chain_arr)
                    if seq:
                        seqs.append(seq)
                except Exception:
                    pass

            if not seqs:
                continue

            ll, _ = _score_role(model, seqs, device)
            n_residues = sum(len(s) for s in seqs)

            yield {
                "grain": "role",
                **self.role_identity_row(ctx, role_name=role_name),
                "n_chains": len(seqs),
                "n_residues": n_residues,
                "ll": ll,
            }
