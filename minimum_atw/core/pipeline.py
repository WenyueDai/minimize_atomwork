"""Public pipeline API: orchestration plus re-exported helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..plugins.dataset.calculation.runtime import analyze_dataset_outputs
from ..runtime.chunked import (
    merge_planned_chunks,         # noqa: F401 — re-exported
    plan_chunked_pipeline,        # noqa: F401 — re-exported
    run_chunked_pipeline,         # noqa: F401 — re-exported
)
from ..runtime.slurm import (
    submit_slurm_chunked_pipeline,  # noqa: F401 — re-exported
    submit_slurm_plan,              # noqa: F401 — re-exported
)
from ..runtime.workspace import copy_final_outputs as _copy_final_outputs
from ._execute import run_plugin, run_plugins  # noqa: F401 — re-exported
from ._prepare import prepare_outputs          # noqa: F401 — re-exported
from ._merge import merge_dataset_outputs, merge_outputs  # noqa: F401 — re-exported
from .config import Config


def _run_dataset_analyses(cfg: Config, out_dir: Path) -> None:
    if not cfg.dataset_analyses:
        return
    print(f"[pipeline] dataset_analyses start analyses={','.join(cfg.dataset_analyses)}", flush=True)
    analyze_dataset_outputs(
        out_dir,
        dataset_analyses=tuple(cfg.dataset_analyses),
        dataset_analysis_params=cfg.dataset_analysis_params,
        dataset_annotations=cfg.dataset_annotations,
        reference_dataset_dir=cfg.reference_dataset_dir,
        cleanup_prepared_after_dataset_analysis=cfg.cleanup_prepared_after_dataset_analysis,
    )
    print("[pipeline] dataset_analyses complete", flush=True)


def run_pipeline(cfg: Config) -> dict[str, int]:
    """Execute the complete pipeline end-to-end: prepare → execute → merge → analyze."""
    out_dir = Path(cfg.out_dir).resolve()
    print(f"[pipeline] run start out_dir={out_dir}", flush=True)
    if cfg.keep_intermediate_outputs:
        print("[pipeline] stage=prepare", flush=True)
        prepare_outputs(cfg)
        print("[pipeline] stage=execute", flush=True)
        run_plugins(cfg, cfg.plugins)
        print("[pipeline] stage=merge", flush=True)
        counts = merge_outputs(cfg)
        if cfg.dataset_analyses:
            _run_dataset_analyses(cfg, out_dir)
        print(f"[pipeline] run complete counts={counts}", flush=True)
        return counts

    with tempfile.TemporaryDirectory(prefix="minimum_atw_run_") as tmp_dir:
        temp_cfg = cfg.model_copy(update={"out_dir": str(Path(tmp_dir).resolve())})
        print(f"[pipeline] temp_out_dir={temp_cfg.out_dir}", flush=True)
        print("[pipeline] stage=prepare", flush=True)
        prepare_outputs(temp_cfg)
        print("[pipeline] stage=execute", flush=True)
        run_plugins(temp_cfg, temp_cfg.plugins)
        print("[pipeline] stage=merge", flush=True)
        counts = merge_outputs(temp_cfg)
        print("[pipeline] stage=copy_final_outputs", flush=True)
        _copy_final_outputs(Path(temp_cfg.out_dir).resolve(), out_dir, cfg=temp_cfg)
        if cfg.dataset_analyses:
            _run_dataset_analyses(cfg, out_dir)
    print(f"[pipeline] run complete counts={counts}", flush=True)
    return counts
