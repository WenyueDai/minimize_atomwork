from __future__ import annotations

import concurrent.futures
from contextlib import ExitStack
from dataclasses import dataclass
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from ..core._schedule import plugin_execution_metadata
from ..core.config import Config
from ..plugins.dataset.calculation.runtime import analyze_dataset_outputs
from ._pool import process_or_thread_pool as _process_or_thread_pool
from .workspace import (
    chunk_dir_name,
    chunk_input_paths,
    clear_final_outputs,
    discover_inputs,
    prepare_chunk_input_dir,
)


CHUNK_PLAN_NAME = "chunk_plan.json"


@dataclass(frozen=True)
class ChunkWorkerPlan:
    requested_workers: int
    effective_workers: int
    cpu_capacity: int
    cpu_workers_per_chunk: int
    gpu_workers_per_chunk: int
    gpu_devices: tuple[str, ...]
    gpu_slot_devices: tuple[tuple[str, ...], ...]
    resource_waves: tuple["ChunkWaveResources", ...]
    submission_plan: dict[str, Any]
    scheduling_errors: tuple[str, ...]


@dataclass(frozen=True)
class ChunkWaveResources:
    wave: int
    cpu_workers: int
    gpu_workers: int
    group_ids: tuple[int, ...]


def _log(message: str) -> None:
    print(message, flush=True)


def _positive_int_from_env(name: str) -> int | None:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value < 1:
        return None
    return value


def _cpu_capacity(cfg: Config) -> int:
    if cfg.chunk_cpu_capacity is not None:
        return int(cfg.chunk_cpu_capacity)
    candidates = [
        _positive_int_from_env("MINIMUM_ATW_CHUNK_CPU_CAPACITY"),
        _positive_int_from_env("SLURM_CPUS_PER_TASK"),
        _positive_int_from_env("SLURM_CPUS_ON_NODE"),
        _positive_int_from_env("OMP_NUM_THREADS"),
    ]
    resolved = [value for value in candidates if value is not None]
    if resolved:
        return min(resolved)
    return max(1, int(os.cpu_count() or 1))


def _gpu_devices_for_chunking(cfg: Config) -> list[str]:
    if cfg.gpu_devices:
        return [str(device) for device in cfg.gpu_devices if str(device).strip()]
    for env_name in ("CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES"):
        raw = str(os.environ.get(env_name, "") or "").strip()
        if not raw or raw.lower() in {"none", "void", "-1", "all"}:
            continue
        return [
            item.strip()
            for item in raw.split(",")
            if item.strip() and item.strip().lower() not in {"none", "void", "-1"}
        ]
    return []


def _chunk_wave_resources(execution_metadata: dict[str, Any]) -> tuple[ChunkWaveResources, ...]:
    grouped: dict[int, dict[str, Any]] = {}
    for group in execution_metadata.get("groups", []):
        wave = int(group.get("wave") or 0)
        entry = grouped.setdefault(
            wave,
            {
                "wave": wave,
                "cpu_workers": 0,
                "gpu_workers": 0,
                "group_ids": [],
            },
        )
        worker_pool = str(group.get("worker_pool", "cpu")).strip().lower()
        planned_cpu_threads = int(group.get("planned_cpu_threads") or 0)
        planned_gpu_devices = int(group.get("planned_gpu_devices") or 0)
        if planned_cpu_threads <= 0:
            planned_workers = max(1, int(group.get("planned_workers") or 1))
            planned_cpu_threads = planned_workers
        entry["cpu_workers"] += planned_cpu_threads
        if worker_pool == "gpu":
            if planned_gpu_devices <= 0:
                planned_gpu_devices = max(1, int(group.get("planned_workers") or 1))
            entry["gpu_workers"] += planned_gpu_devices
        if "group_id" in group:
            entry["group_ids"].append(int(group["group_id"]))

    return tuple(
        ChunkWaveResources(
            wave=int(entry["wave"]),
            cpu_workers=int(entry["cpu_workers"]),
            gpu_workers=int(entry["gpu_workers"]),
            group_ids=tuple(sorted(int(group_id) for group_id in entry["group_ids"])),
        )
        for _, entry in sorted(grouped.items())
    )


def _chunk_submission_plan(execution_metadata: dict[str, Any]) -> dict[str, Any]:
    scheduler_resources = dict(execution_metadata.get("scheduler_resources") or {})
    submission_plan = dict(scheduler_resources.get("submission_plan") or {})
    single_job = dict(scheduler_resources.get("single_job") or {})

    stages: list[dict[str, Any]] = []
    for stage in list(submission_plan.get("stages") or []):
        stage_jobs: list[dict[str, Any]] = []
        for job in list(stage.get("jobs") or []):
            cpu_threads = int(job.get("cpu_threads") or 0)
            gpu_devices = int(job.get("gpu_devices") or 0)
            stage_jobs.append(
                {
                    "job_id": str(job.get("job_id") or ""),
                    "worker_pool": str(job.get("worker_pool") or "cpu"),
                    "resource_class": str(job.get("resource_class") or "cpu_only"),
                    "device_kind": str(job.get("device_kind") or "cpu"),
                    "cpu_threads": cpu_threads,
                    "gpu_devices": gpu_devices,
                    "group_ids": [int(group_id) for group_id in list(job.get("group_ids") or [])],
                    "plugins": [str(name) for name in list(job.get("plugins") or [])],
                    "recommended_chunk_job": {
                        "cpu_threads": cpu_threads,
                        "gpu_devices": gpu_devices,
                    },
                }
            )
        stages.append(
            {
                "stage": int(stage.get("stage") or 0),
                "worker_pools": [str(pool) for pool in list(stage.get("worker_pools") or [])],
                "cpu_threads": int(stage.get("cpu_threads") or 0),
                "gpu_devices": int(stage.get("gpu_devices") or 0),
                "jobs": stage_jobs,
            }
        )

    job_classes = []
    for entry in list(submission_plan.get("job_classes") or []):
        cpu_threads = int(entry.get("peak_cpu_threads") or 0)
        gpu_devices = int(entry.get("peak_gpu_devices") or 0)
        job_classes.append(
            {
                "worker_pool": str(entry.get("worker_pool") or "cpu"),
                "resource_class": str(entry.get("resource_class") or "cpu_only"),
                "device_kind": str(entry.get("device_kind") or "cpu"),
                "peak_cpu_threads": cpu_threads,
                "peak_gpu_devices": gpu_devices,
                "stages": [int(stage) for stage in list(entry.get("stages") or [])],
                "recommended_chunk_job": {
                    "cpu_threads": cpu_threads,
                    "gpu_devices": gpu_devices,
                },
            }
        )

    return {
        "recommended_mode": str(submission_plan.get("recommended_mode") or "single_job"),
        "reason": str(submission_plan.get("reason") or ""),
        "single_chunk_job": {
            "cpu_threads": int(single_job.get("cpu_threads") or 0),
            "gpu_devices": int(single_job.get("gpu_devices") or 0),
        },
        "stages": stages,
        "job_classes": job_classes,
    }


def _chunk_worker_plan(
    cfg: Config,
    *,
    requested_workers: int,
    n_chunks: int,
    strict: bool = True,
) -> ChunkWorkerPlan:
    requested = max(1, int(requested_workers))
    execution_metadata = plugin_execution_metadata(cfg)
    resource_waves = _chunk_wave_resources(execution_metadata)
    submission_plan = _chunk_submission_plan(execution_metadata)
    scheduling_errors: list[str] = []

    cpu_workers_per_chunk = max(1, max((wave.cpu_workers for wave in resource_waves), default=0))
    cpu_capacity = _cpu_capacity(cfg)
    if cpu_capacity < cpu_workers_per_chunk:
        error = (
            f"Chunk scheduling requires {cpu_workers_per_chunk} CPU workers per chunk "
            f"but only {cpu_capacity} are available on this node"
        )
        if strict:
            raise ValueError(error)
        scheduling_errors.append(error)
        cpu_chunk_limit = 0
    else:
        cpu_chunk_limit = max(1, cpu_capacity // cpu_workers_per_chunk)

    gpu_devices = tuple(_gpu_devices_for_chunking(cfg))
    gpu_workers_per_chunk = max((wave.gpu_workers for wave in resource_waves), default=0)
    if gpu_workers_per_chunk > 0 and gpu_devices and len(gpu_devices) < gpu_workers_per_chunk:
        error = (
            f"Chunk scheduling requires {gpu_workers_per_chunk} GPU devices per chunk "
            f"but only {len(gpu_devices)} visible devices are available"
        )
        if strict:
            raise ValueError(error)
        scheduling_errors.append(error)
        gpu_chunk_limit = 0
        gpu_slot_devices = tuple()
    elif gpu_workers_per_chunk > 0:
        if gpu_devices:
            gpu_chunk_limit = max(1, len(gpu_devices) // gpu_workers_per_chunk)
            gpu_slot_devices = tuple(
                tuple(gpu_devices[idx * gpu_workers_per_chunk : (idx + 1) * gpu_workers_per_chunk])
                for idx in range(gpu_chunk_limit)
            )
        else:
            gpu_chunk_limit = 1
            gpu_slot_devices = (tuple(),)
    else:
        gpu_chunk_limit = requested
        gpu_slot_devices = tuple(tuple() for _ in range(max(1, requested)))

    effective = min(requested, n_chunks, cpu_chunk_limit, gpu_chunk_limit)
    if strict:
        effective = max(1, effective)
    else:
        effective = max(0, effective)
    return ChunkWorkerPlan(
        requested_workers=requested,
        effective_workers=effective,
        cpu_capacity=cpu_capacity,
        cpu_workers_per_chunk=cpu_workers_per_chunk,
        gpu_workers_per_chunk=gpu_workers_per_chunk,
        gpu_devices=gpu_devices,
        gpu_slot_devices=gpu_slot_devices[:effective],
        resource_waves=resource_waves,
        submission_plan=submission_plan,
        scheduling_errors=tuple(scheduling_errors),
    )


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


def _submit_chunk_jobs_shared_pool(
    jobs: list[dict[str, Any]],
    *,
    max_workers: int,
) -> list[dict[str, Any]]:
    with _process_or_thread_pool(max_workers=max_workers) as executor:
        futures = [executor.submit(_run_chunk_job, **job) for job in jobs]
        return [future.result() for future in concurrent.futures.as_completed(futures)]


def _drain_chunk_slot_jobs(
    executors: list[concurrent.futures.Executor],
    jobs: list[dict[str, Any]],
    slot_gpu_devices: list[list[str]],
) -> list[dict[str, Any]]:
    pending: dict[concurrent.futures.Future, int] = {}
    next_index = 0
    results: list[dict[str, Any]] = []

    for slot_index, executor in enumerate(executors):
        if next_index >= len(jobs):
            break
        future = executor.submit(
            _run_chunk_job,
            **{**jobs[next_index], "assigned_gpu_devices": slot_gpu_devices[slot_index]},
        )
        pending[future] = slot_index
        next_index += 1

    while pending:
        done, _ = concurrent.futures.wait(
            set(pending),
            return_when=concurrent.futures.FIRST_COMPLETED,
        )
        for future in done:
            slot_index = pending.pop(future)
            results.append(future.result())
            if next_index < len(jobs):
                new_future = executors[slot_index].submit(
                    _run_chunk_job,
                    **{**jobs[next_index], "assigned_gpu_devices": slot_gpu_devices[slot_index]},
                )
                pending[new_future] = slot_index
                next_index += 1

    return results


def _submit_chunk_jobs_gpu_slots(
    jobs: list[dict[str, Any]],
    *,
    slot_gpu_devices: list[list[str]],
) -> list[dict[str, Any]]:
    with ExitStack() as stack:
        executors = [
            stack.enter_context(_process_or_thread_pool(max_workers=1))
            for _ in slot_gpu_devices
        ]
        return _drain_chunk_slot_jobs(executors, jobs, slot_gpu_devices)


def _run_chunk_job(
    *,
    config_data: dict[str, Any],
    chunk_paths: list[str],
    chunk_index: int,
    workspace_dir: str,
    assigned_gpu_devices: list[str] | None = None,
) -> dict[str, Any]:
    from ..core.pipeline import run_pipeline

    workspace_path = Path(workspace_dir).resolve()
    chunk_dir = workspace_path / chunk_dir_name(chunk_index)
    chunk_input_dir = chunk_dir / "input"
    chunk_out_dir = chunk_dir / "out"
    prepare_chunk_input_dir(chunk_input_dir, [Path(path).resolve() for path in chunk_paths])

    chunk_config_data = _chunk_config_data(
        config_data,
        chunk_input_dir=chunk_input_dir,
        chunk_out_dir=chunk_out_dir,
    )
    if assigned_gpu_devices:
        chunk_config_data["gpu_devices"] = list(assigned_gpu_devices)
    chunk_cfg = Config(**chunk_config_data)
    counts = run_pipeline(chunk_cfg)
    return {
        "chunk_index": chunk_index,
        "chunk_input_dir": str(chunk_input_dir),
        "chunk_out_dir": str(chunk_out_dir),
        "n_input_files": len(chunk_paths),
        "assigned_gpu_devices": list(chunk_cfg.gpu_devices),
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
    resource_plan = _chunk_worker_plan(cfg, requested_workers=len(chunks), n_chunks=len(chunks), strict=False)
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
                "resource_plan": {
                    "cpu_capacity": int(resource_plan.cpu_capacity),
                    "cpu_workers_per_chunk": int(resource_plan.cpu_workers_per_chunk),
                    "cpu_threads_per_chunk": int(resource_plan.cpu_workers_per_chunk),
                    "gpu_workers_per_chunk": int(resource_plan.gpu_workers_per_chunk),
                    "gpu_devices_per_chunk": int(resource_plan.gpu_workers_per_chunk),
                    "gpu_devices": list(resource_plan.gpu_devices),
                    "max_concurrent_chunks": int(resource_plan.effective_workers),
                    "recommended_chunk_job": {
                        "cpu_threads": int(resource_plan.cpu_workers_per_chunk),
                        "gpu_devices": int(resource_plan.gpu_workers_per_chunk),
                    },
                    "submission_plan": resource_plan.submission_plan,
                    "scheduling_errors": list(resource_plan.scheduling_errors),
                    "waves": [
                        {
                            "wave": int(wave.wave),
                            "cpu_workers": int(wave.cpu_workers),
                            "gpu_workers": int(wave.gpu_workers),
                            "group_ids": list(wave.group_ids),
                        }
                        for wave in resource_plan.resource_waves
                    ],
                },
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
            reference_dataset_dir=source_config.reference_dataset_dir,
            cleanup_prepared_after_dataset_analysis=source_config.cleanup_prepared_after_dataset_analysis,
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
    worker_plan = _chunk_worker_plan(cfg, requested_workers=workers, n_chunks=len(chunks))
    max_workers = int(worker_plan.effective_workers)
    out_dir = Path(cfg.out_dir).resolve()
    clear_final_outputs(out_dir)
    _log(
        "[chunked] "
        f"requested_workers={worker_plan.requested_workers} "
        f"effective_workers={worker_plan.effective_workers} "
        f"cpu_capacity={worker_plan.cpu_capacity} "
        f"cpu_workers_per_chunk={worker_plan.cpu_workers_per_chunk}"
    )
    if worker_plan.submission_plan:
        _log(
            "[chunked] "
            f"scheduler_mode={worker_plan.submission_plan.get('recommended_mode', 'single_job')}"
        )
    if worker_plan.resource_waves:
        _log(
            "[chunked] "
            + "wave_resources="
            + ";".join(
                f"wave{wave.wave}:cpu_threads={wave.cpu_workers},gpu_devices={wave.gpu_workers}"
                for wave in worker_plan.resource_waves
            )
        )
    if worker_plan.gpu_workers_per_chunk > 0:
        if worker_plan.gpu_devices:
            _log(
                "[chunked] "
                f"gpu_devices_per_chunk={worker_plan.gpu_workers_per_chunk} "
                f"visible_gpu_devices={','.join(worker_plan.gpu_devices)}"
            )
        else:
            _log(
                "[chunked] "
                f"gpu_devices_per_chunk={worker_plan.gpu_workers_per_chunk} "
                "visible_gpu_devices=unknown forcing_serial_gpu_chunks=true"
            )

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

        if max_workers == 1:
            chunk_results = [_run_chunk_job(**job) for job in jobs]
        elif worker_plan.gpu_workers_per_chunk > 0 and worker_plan.gpu_devices:
            slot_gpu_devices = [list(devices) for devices in worker_plan.gpu_slot_devices]
            _log(
                "[chunked] "
                f"gpu_chunk_slots={';'.join(','.join(slot) for slot in slot_gpu_devices)}"
            )
            chunk_results = _submit_chunk_jobs_gpu_slots(
                jobs,
                slot_gpu_devices=slot_gpu_devices,
            )
        else:
            chunk_results = _submit_chunk_jobs_shared_pool(
                jobs,
                max_workers=max_workers,
            )

        chunk_results = sorted(chunk_results, key=lambda item: int(item["chunk_index"]))
        merged_counts = merge_dataset_outputs([item["chunk_out_dir"] for item in chunk_results], out_dir)
        if cfg.should_run_post_merge_dataset_analyses():
            analyze_dataset_outputs(
                out_dir,
                dataset_analyses=tuple(cfg.dataset_analyses),
                dataset_analysis_params=cfg.dataset_analysis_params,
                dataset_annotations=cfg.dataset_annotations,
                reference_dataset_dir=cfg.reference_dataset_dir,
                cleanup_prepared_after_dataset_analysis=cfg.cleanup_prepared_after_dataset_analysis,
            )

    merged_counts["chunks"] = len(chunks)
    merged_counts["chunk_size"] = chunk_size
    merged_counts["workers"] = max_workers
    merged_counts["workers_requested"] = int(worker_plan.requested_workers)
    merged_counts["cpu_capacity"] = int(worker_plan.cpu_capacity)
    merged_counts["cpu_workers_per_chunk"] = int(worker_plan.cpu_workers_per_chunk)
    if worker_plan.gpu_workers_per_chunk > 0:
        merged_counts["gpu_workers_per_chunk"] = int(worker_plan.gpu_workers_per_chunk)
    return merged_counts
