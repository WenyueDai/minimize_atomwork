"""Public pipeline API: orchestration plus re-exported merge/execute helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..plugins.dataset.calculation.runtime import analyze_dataset_outputs
from ..runtime.chunked import (
    merge_planned_chunks as _merge_planned_chunks,
    plan_chunked_pipeline as _plan_chunked_pipeline,
    run_chunked_pipeline as _run_chunked_pipeline,
)
from ..runtime.workspace import copy_final_outputs as _copy_final_outputs
from ._execute import run_plugin, run_plugins  # noqa: F401 — re-exported
from ._prepare import prepare_execution_metadata as _prepare_execution_metadata
from ._prepare import prepare_outputs  # noqa: F401 — re-exported
from ._merge import merge_dataset_outputs, merge_outputs  # noqa: F401 — re-exported
from .config import Config


def _run_dataset_analyses(cfg: Config, out_dir: Path) -> None:
    if not cfg.dataset_analyses:
        return
    analyze_dataset_outputs(
        out_dir,
        dataset_analyses=tuple(cfg.dataset_analyses),
        dataset_analysis_params=cfg.dataset_analysis_params,
        dataset_annotations=cfg.dataset_annotations,
    )


def run_pipeline(cfg: Config) -> dict[str, int]:
    """Execute the complete pipeline end-to-end: prepare → execute → merge → analyze."""
    out_dir = Path(cfg.out_dir).resolve()
    if cfg.keep_intermediate_outputs:
        prepare_outputs(cfg)
        run_plugins(cfg, cfg.plugins)
        counts = merge_outputs(cfg)
        if cfg.dataset_analyses:
            _run_dataset_analyses(cfg, out_dir)
        return counts

    with tempfile.TemporaryDirectory(prefix="minimum_atw_run_") as tmp_dir:
        temp_cfg = cfg.model_copy(update={"out_dir": str(Path(tmp_dir).resolve())})
        prepare_outputs(temp_cfg)
        run_plugins(temp_cfg, temp_cfg.plugins)
        counts = merge_outputs(temp_cfg)
        _copy_final_outputs(Path(temp_cfg.out_dir).resolve(), out_dir, cfg=temp_cfg)
        if cfg.dataset_analyses:
            _run_dataset_analyses(cfg, out_dir)
    return counts


def run_chunked_pipeline(cfg: Config, *, chunk_size: int, workers: int = 1) -> dict[str, int]:
    """Run the pipeline in parallel over chunked inputs, then merge."""
    return _run_chunked_pipeline(cfg, chunk_size=chunk_size, workers=workers)


def plan_chunked_pipeline(cfg: Config, *, chunk_size: int, plan_dir: str | Path) -> dict[str, int]:
    """Write a chunk plan for offline/cluster execution."""
    return _plan_chunked_pipeline(cfg, chunk_size=chunk_size, plan_dir=plan_dir)


def merge_planned_chunks(plan_dir: str | Path, *, out_dir: str | Path | None = None) -> dict[str, int]:
    """Merge outputs from a previously planned chunked run."""
    return _merge_planned_chunks(plan_dir, out_dir=out_dir)
