from __future__ import annotations

import concurrent.futures
import tempfile
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .workspace import (
    chunk_dir_name,
    chunk_input_paths,
    clear_final_outputs,
    discover_inputs,
    prepare_chunk_input_dir,
)


def _run_chunk_job(
    *,
    config_data: dict[str, Any],
    chunk_paths: list[str],
    chunk_index: int,
    workspace_dir: str,
) -> dict[str, Any]:
    from .pipeline import run_pipeline

    workspace_path = Path(workspace_dir).resolve()
    chunk_dir = workspace_path / chunk_dir_name(chunk_index)
    chunk_input_dir = chunk_dir / "input"
    chunk_out_dir = chunk_dir / "out"
    prepare_chunk_input_dir(chunk_input_dir, [Path(path).resolve() for path in chunk_paths])

    chunk_cfg = Config(**config_data).model_copy(
        update={
            "input_dir": str(chunk_input_dir),
            "out_dir": str(chunk_out_dir),
            "keep_intermediate_outputs": False,
            "dataset_analyses": [],
        }
    )
    counts = run_pipeline(chunk_cfg)
    return {
        "chunk_index": chunk_index,
        "chunk_input_dir": str(chunk_input_dir),
        "chunk_out_dir": str(chunk_out_dir),
        "n_input_files": len(chunk_paths),
        "counts": counts,
    }


def run_chunked_pipeline(
    cfg: Config,
    *,
    chunk_size: int,
    workers: int,
    merge_dataset_outputs_fn: Callable[[list[str | Path], str | Path], dict[str, int]],
    analyze_dataset_outputs_fn: Callable[..., dict[str, int | str]],
) -> dict[str, int]:
    input_paths = discover_inputs(Path(cfg.input_dir).resolve())
    if not input_paths:
        raise FileNotFoundError(f"No .pdb or .cif files found in {Path(cfg.input_dir).resolve()}")

    chunks = chunk_input_paths(input_paths, chunk_size)
    max_workers = max(1, int(workers))
    out_dir = Path(cfg.out_dir).resolve()
    clear_final_outputs(out_dir)

    config_data = cfg.model_dump()
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
        merged_counts = merge_dataset_outputs_fn([item["chunk_out_dir"] for item in chunk_results], out_dir)
        if cfg.dataset_analyses:
            analyze_dataset_outputs_fn(
                out_dir,
                dataset_analyses=tuple(cfg.dataset_analyses),
                dataset_annotations=cfg.dataset_annotations,
            )

    merged_counts["chunks"] = len(chunks)
    merged_counts["chunk_size"] = chunk_size
    merged_counts["workers"] = max_workers
    return merged_counts
