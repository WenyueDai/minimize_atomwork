from __future__ import annotations

from typing import Any


def _resolve_device(param: str) -> str:
    """Resolve 'auto' to 'cuda' or 'cpu'; pass digit strings as 'cuda:N'."""
    normalized = str(param or "auto").strip().lower()
    if normalized == "auto":
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
    if normalized.isdigit():
        return f"cuda:{normalized}"
    return normalized or "cpu"


def _gpu_scheduling(base: dict[str, Any], cfg: Any, plugin_name: str) -> dict[str, Any]:
    """Augment a scheduling dict with GPU pool settings derived from cfg."""
    params = dict(getattr(cfg, "plugin_params", {}).get(plugin_name, {})) if cfg is not None else {}
    device = str(params.get("device", "auto") or "auto").strip().lower()
    gpu_budget = 0
    if cfg is not None:
        gpu_budget = max(int(getattr(cfg, "gpu_workers", 0)), len(getattr(cfg, "gpu_devices", []) or []))
    use_gpu_pool = device.startswith("cuda") or device.isdigit() or (device == "auto" and gpu_budget > 0)
    base["device_kind"] = "cuda" if use_gpu_pool else (device or "auto")
    base["worker_pool"] = "gpu" if use_gpu_pool else "cpu"
    return base
