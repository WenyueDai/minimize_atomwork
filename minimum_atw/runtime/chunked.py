from __future__ import annotations

import concurrent.futures
import json
import tempfile
from pathlib import Path
from typing import Any

import yaml

from ..core.config import Config
from ..plugins.dataset_analysis.runtime import analyze_dataset_outputs
from .workspace import (
    chunk_dir_name,
    chunk_input_paths,
    clear_final_outputs,
    discover_inputs,
    prepare_chunk_input_dir,
)


CHUNK_PLAN_NAME = "chunk_plan.json"


def _chunk_config_data(
    config_data: dict[str, Any],
    *,
    chunk_input_dir: Path,
    chunk_out_dir: Path,
) -> dict[str, Any]:
    source_config = Config(**config_data)
    return source_config.chunk_config(
        input_dir=chunk_input_dir,
        out_dir=chunk_out_dir,
    ).model_dump(mode="json")


def _read_chunk_plan(plan_dir: Path) -> dict[str, Any]:
    plan_path = plan_dir / CHUNK_PLAN_NAME
    if not plan_path.exists():
        raise FileNotFoundError(f"Chunk plan not found: {plan_path}")
    return json.loads(plan_path.read_text())


def _run_chunk_job(
    *,
    config_data: dict[str, Any],
    chunk_paths: list[str],
    chunk_index: int,
    workspace_dir: str,
) -> dict[str, Any]:
    from ..core.pipeline import run_pipeline

    workspace_path = Path(workspace_dir).resolve()
    chunk_dir = workspace_path / chunk_dir_name(chunk_index)
    chunk_input_dir = chunk_dir / "input"
    chunk_out_dir = chunk_dir / "out"
    prepare_chunk_input_dir(chunk_input_dir, [Path(path).resolve() for path in chunk_paths])

    chunk_cfg = Config(**_chunk_config_data(
        config_data,
        chunk_input_dir=chunk_input_dir,
        chunk_out_dir=chunk_out_dir,
    ))
    counts = run_pipeline(chunk_cfg)
    return {
        "chunk_index": chunk_index,
        "chunk_input_dir": str(chunk_input_dir),
        "chunk_out_dir": str(chunk_out_dir),
        "n_input_files": len(chunk_paths),
        "counts": counts,
    }


def plan_chunked_pipeline(
    cfg: Config,
    *,
    chunk_size: int,
    plan_dir: str | Path,
) -> dict[str, int]:
    input_paths = discover_inputs(Path(cfg.input_dir).resolve())
    if not input_paths:
        raise FileNotFoundError(f"No .pdb or .cif files found in {Path(cfg.input_dir).resolve()}")

    target_plan_dir = Path(plan_dir).resolve()
    if target_plan_dir.exists() and any(target_plan_dir.iterdir()):
        raise FileExistsError(f"Chunk plan directory already exists and is not empty: {target_plan_dir}")
    target_plan_dir.mkdir(parents=True, exist_ok=True)

    config_data = cfg.model_dump(mode="json")
    chunks = chunk_input_paths(input_paths, chunk_size)
    chunk_records: list[dict[str, Any]] = []

    for chunk_index, chunk_paths in enumerate(chunks, start=1):
        chunk_dir = target_plan_dir / chunk_dir_name(chunk_index)
        chunk_input_dir = chunk_dir / "input"
        chunk_out_dir = chunk_dir / "out"
        chunk_config_path = chunk_dir / "config.yaml"

        prepare_chunk_input_dir(chunk_input_dir, chunk_paths)
        chunk_config = _chunk_config_data(
            config_data,
            chunk_input_dir=chunk_input_dir,
            chunk_out_dir=chunk_out_dir,
        )
        chunk_config_path.write_text(yaml.safe_dump(chunk_config, sort_keys=False))
        chunk_records.append(
            {
                "chunk_index": chunk_index,
                "chunk_dir": str(chunk_dir),
                "chunk_input_dir": str(chunk_input_dir),
                "chunk_out_dir": str(chunk_out_dir),
                "chunk_config_path": str(chunk_config_path),
                "n_input_files": len(chunk_paths),
                "input_files": [str(path.resolve()) for path in chunk_paths],
            }
        )

    (target_plan_dir / CHUNK_PLAN_NAME).write_text(
        json.dumps(
            {
                "output_kind": "chunk_plan",
                "source_config": config_data,
                "chunk_size": chunk_size,
                "planned_structures": len(input_paths),
                "chunks": chunk_records,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return {
        "chunks": len(chunks),
        "chunk_size": chunk_size,
        "planned_structures": len(input_paths),
    }


def merge_planned_chunks(
    plan_dir: str | Path,
    *,
    out_dir: str | Path | None = None,
) -> dict[str, int]:
    from ..core.pipeline import merge_dataset_outputs

    resolved_plan_dir = Path(plan_dir).resolve()
    plan = _read_chunk_plan(resolved_plan_dir)
    source_config = Config(**dict(plan["source_config"]))
    target_out_dir = Path(out_dir).resolve() if out_dir is not None else Path(source_config.out_dir).resolve()
    chunk_out_dirs = [str(Path(item["chunk_out_dir"]).resolve()) for item in plan["chunks"]]

    counts = merge_dataset_outputs(chunk_out_dirs, target_out_dir)
    if source_config.should_run_post_merge_dataset_analyses():
        analyze_dataset_outputs(
            target_out_dir,
            dataset_analyses=tuple(source_config.dataset_analyses),
            dataset_analysis_params=source_config.dataset_analysis_params,
            dataset_annotations=source_config.dataset_annotations,
        )

    counts["chunks"] = len(plan["chunks"])
    counts["chunk_size"] = int(plan["chunk_size"])
    return counts


def run_chunked_pipeline(
    cfg: Config,
    *,
    chunk_size: int,
    workers: int,
) -> dict[str, int]:
    from ..core.pipeline import merge_dataset_outputs

    input_paths = discover_inputs(Path(cfg.input_dir).resolve())
    if not input_paths:
        raise FileNotFoundError(f"No .pdb or .cif files found in {Path(cfg.input_dir).resolve()}")

    chunks = chunk_input_paths(input_paths, chunk_size)
    max_workers = max(1, int(workers))
    out_dir = Path(cfg.out_dir).resolve()
    clear_final_outputs(out_dir)

    config_data = cfg.model_dump(mode="json")
    with tempfile.TemporaryDirectory(prefix="minimum_atw_chunked_") as tmp_dir:
        workspace_dir = Path(tmp_dir).resolve()

        jobs = [
            {
                "config_data": config_data,
                "chunk_paths": [str(path) for path in chunk_paths],
                "chunk_index": chunk_index,
                "workspace_dir": str(workspace_dir),
            }
            for chunk_index, chunk_paths in enumerate(chunks, start=1)
        ]

        def submit_all(executor):
            futures = [executor.submit(_run_chunk_job, **job) for job in jobs]
            return [future.result() for future in concurrent.futures.as_completed(futures)]

        if max_workers == 1:
            chunk_results = [_run_chunk_job(**job) for job in jobs]
        else:
            try:
                with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                    chunk_results = submit_all(executor)
            except PermissionError:
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    chunk_results = submit_all(executor)

        chunk_results = sorted(chunk_results, key=lambda item: int(item["chunk_index"]))
        merged_counts = merge_dataset_outputs([item["chunk_out_dir"] for item in chunk_results], out_dir)
        if cfg.should_run_post_merge_dataset_analyses():
            analyze_dataset_outputs(
                out_dir,
                dataset_analyses=tuple(cfg.dataset_analyses),
                dataset_analysis_params=cfg.dataset_analysis_params,
                dataset_annotations=cfg.dataset_annotations,
            )

    merged_counts["chunks"] = len(chunks)
    merged_counts["chunk_size"] = chunk_size
    merged_counts["workers"] = max_workers
    return merged_counts
