"""Plugin scheduling: execution planning, wave assignment, and resource metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Config


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PluginExecutionSpec:
    name: str
    plugin: Any
    input_model: str
    execution_mode: str
    worker_pool: str
    device_kind: str
    max_workers: int | None
    cpu_threads_per_worker: int
    gpu_devices_per_worker: int
    failure_policy: str


@dataclass(frozen=True)
class PlannedPluginGroup:
    group_id: int
    specs: tuple[PluginExecutionSpec, ...]
    depends_on_group_ids: tuple[int, ...]
    wave: int


# ---------------------------------------------------------------------------
# Spec resolution
# ---------------------------------------------------------------------------

def _plugin_execution_spec(plugin_name: str, cfg: Config) -> PluginExecutionSpec:
    from ..plugins import PLUGIN_REGISTRY
    from .registry import instantiate_unit

    if plugin_name not in PLUGIN_REGISTRY:
        raise KeyError(f"Unknown plugin: {plugin_name}")
    plugin = instantiate_unit(PLUGIN_REGISTRY[plugin_name])
    if hasattr(plugin, "scheduling"):
        scheduling = dict(plugin.scheduling(cfg))
    else:
        scheduling = {}

    input_model = str(scheduling.get("input_model") or getattr(plugin, "input_model", "atom_array")).strip().lower()
    execution_mode = str(scheduling.get("execution_mode") or getattr(plugin, "execution_mode", "batched")).strip().lower()
    worker_pool = str(scheduling.get("worker_pool") or getattr(plugin, "worker_pool", "cpu")).strip().lower()
    device_kind = str(scheduling.get("device_kind") or getattr(plugin, "device_kind", "cpu")).strip().lower()
    raw_max_workers = scheduling.get("max_workers", getattr(plugin, "max_workers", None))
    max_workers = None if raw_max_workers in {None, ""} else max(1, int(raw_max_workers))
    raw_cpu_threads = scheduling.get("cpu_threads_per_worker", getattr(plugin, "cpu_threads_per_worker", None))
    cpu_threads_per_worker = 1 if raw_cpu_threads in {None, ""} else max(1, int(raw_cpu_threads))
    raw_gpu_devices = scheduling.get("gpu_devices_per_worker", getattr(plugin, "gpu_devices_per_worker", None))
    if raw_gpu_devices in {None, ""}:
        gpu_devices_per_worker = 1 if worker_pool == "gpu" else 0
    else:
        gpu_devices_per_worker = max(0, int(raw_gpu_devices))
    if worker_pool != "gpu":
        gpu_devices_per_worker = 0
    elif gpu_devices_per_worker < 1:
        gpu_devices_per_worker = 1
    if gpu_devices_per_worker > 1:
        raise ValueError(
            f"Plugin '{plugin_name}' requests gpu_devices_per_worker={gpu_devices_per_worker}, "
            "but the current dispatcher only supports one GPU device per worker"
        )
    return PluginExecutionSpec(
        name=plugin_name,
        plugin=plugin,
        input_model=input_model or "atom_array",
        execution_mode=execution_mode or "batched",
        worker_pool=worker_pool or "cpu",
        device_kind=device_kind or "cpu",
        max_workers=max_workers,
        cpu_threads_per_worker=cpu_threads_per_worker,
        gpu_devices_per_worker=gpu_devices_per_worker,
        failure_policy=str(getattr(plugin, "failure_policy", "continue") or "continue").strip().lower(),
    )


def resolve_plugin_specs(plugin_names: list[str], cfg: Config) -> list[PluginExecutionSpec]:
    return [_plugin_execution_spec(name, cfg) for name in plugin_names]


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def _group_signature(spec: PluginExecutionSpec) -> tuple[str, str, str, str, int | None]:
    return (spec.input_model, spec.execution_mode, spec.worker_pool, spec.device_kind, spec.max_workers)


def _can_extend_group(group: list[PluginExecutionSpec], spec: PluginExecutionSpec) -> bool:
    if not group:
        return True
    if _group_signature(group[0]) != _group_signature(spec):
        return False
    group_names = {item.name for item in group}
    return not any(req in group_names for req in getattr(spec.plugin, "requires", []))


def plan_plugin_execution(specs: list[PluginExecutionSpec]) -> list[list[PluginExecutionSpec]]:
    """Return pool-compatible groups in topological order, respecting 'requires'."""
    spec_by_name = {spec.name: spec for spec in specs}
    configured = set(spec_by_name)

    for spec in specs:
        missing = [r for r in getattr(spec.plugin, "requires", []) if r not in configured]
        if missing:
            raise ValueError(f"Plugin '{spec.name}' requires plugins not configured: {missing}")

    order: list[PluginExecutionSpec] = []
    visited: set[str] = set()

    def _visit(name: str, visiting: frozenset[str]) -> None:
        if name in visited:
            return
        if name in visiting:
            raise ValueError(f"Circular dependency: {' -> '.join(sorted(visiting))} -> {name}")
        visiting = visiting | {name}
        for req in getattr(spec_by_name[name].plugin, "requires", []):
            if req in spec_by_name:
                _visit(req, visiting)
        visited.add(name)
        order.append(spec_by_name[name])

    for spec in specs:
        _visit(spec.name, frozenset())

    groups: list[list[PluginExecutionSpec]] = []
    current_group: list[PluginExecutionSpec] = []
    for spec in order:
        if current_group and not _can_extend_group(current_group, spec):
            groups.append(current_group)
            current_group = []
        current_group.append(spec)
    if current_group:
        groups.append(current_group)
    return groups


def plan_plugin_groups(specs: list[PluginExecutionSpec]) -> list[PlannedPluginGroup]:
    grouped_specs = plan_plugin_execution(specs)
    plugin_to_group: dict[str, int] = {}
    planned: list[PlannedPluginGroup] = []
    pools_by_wave: list[set[str]] = []
    waves_by_group: list[int] = []

    for group_id, group in enumerate(grouped_specs):
        depends_on = sorted(
            {
                plugin_to_group[req]
                for spec in group
                for req in getattr(spec.plugin, "requires", [])
                if req in plugin_to_group
            }
        )
        min_wave = 0 if not depends_on else max(waves_by_group[idx] for idx in depends_on) + 1
        worker_pool = group[0].worker_pool if group else "cpu"
        wave = min_wave
        while wave < len(pools_by_wave) and worker_pool in pools_by_wave[wave]:
            wave += 1
        while wave >= len(pools_by_wave):
            pools_by_wave.append(set())
        pools_by_wave[wave].add(worker_pool)
        planned.append(
            PlannedPluginGroup(
                group_id=group_id,
                specs=tuple(group),
                depends_on_group_ids=tuple(depends_on),
                wave=wave,
            )
        )
        waves_by_group.append(wave)
        for spec in group:
            plugin_to_group[spec.name] = group_id
    return planned


def waves_from_groups(planned_groups: list[PlannedPluginGroup]) -> list[list[PlannedPluginGroup]]:
    waves: list[list[PlannedPluginGroup]] = []
    for group in planned_groups:
        while group.wave >= len(waves):
            waves.append([])
        waves[group.wave].append(group)
    return waves


def plan_plugin_waves(specs: list[PluginExecutionSpec]) -> list[list[PlannedPluginGroup]]:
    return waves_from_groups(plan_plugin_groups(specs))


# ---------------------------------------------------------------------------
# Resource budgets
# ---------------------------------------------------------------------------

def group_cpu_threads_per_worker(group: list[PluginExecutionSpec]) -> int:
    if not group:
        return 1
    return max(1, max(int(spec.cpu_threads_per_worker) for spec in group))


def group_gpu_devices_per_worker(group: list[PluginExecutionSpec]) -> int:
    if not group:
        return 0
    return max(0, max(int(spec.gpu_devices_per_worker) for spec in group))


def group_worker_budget(cfg: Config, group: list[PluginExecutionSpec]) -> int:
    if not group:
        return 1
    head = group[0]
    if head.worker_pool == "gpu":
        budget = int(cfg.gpu_workers) if int(cfg.gpu_workers) > 0 else max(len(cfg.gpu_devices), 1)
        gpu_devices_per_worker = max(1, group_gpu_devices_per_worker(group))
        if cfg.gpu_devices:
            budget = min(budget, max(1, len(cfg.gpu_devices) // gpu_devices_per_worker))
    else:
        budget = max(1, int(cfg.cpu_workers))
    limits = [int(spec.max_workers) for spec in group if spec.max_workers is not None]
    if limits:
        budget = min(budget, min(limits))
    return max(1, budget)


def group_resource_totals(cfg: Config, group: list[PluginExecutionSpec]) -> dict[str, int]:
    planned_workers = group_worker_budget(cfg, group)
    cpu_per = group_cpu_threads_per_worker(group)
    gpu_per = group_gpu_devices_per_worker(group)
    return {
        "planned_workers": int(planned_workers),
        "cpu_threads_per_worker": int(cpu_per),
        "gpu_devices_per_worker": int(gpu_per),
        "planned_cpu_threads": int(planned_workers * cpu_per),
        "planned_gpu_devices": int(planned_workers * gpu_per),
    }


# ---------------------------------------------------------------------------
# Metadata assembly
# ---------------------------------------------------------------------------

def _wave_resource_metadata(
    cfg: Config,
    groups_in_wave: list[PlannedPluginGroup],
    *,
    wave_index: int,
) -> dict[str, Any]:
    cpu_threads = 0
    gpu_devices = 0
    for group in groups_in_wave:
        totals = group_resource_totals(cfg, list(group.specs))
        cpu_threads += int(totals["planned_cpu_threads"])
        gpu_devices += int(totals["planned_gpu_devices"])
    return {
        "wave": int(wave_index),
        "group_ids": [group.group_id for group in groups_in_wave],
        "worker_pools": [group.specs[0].worker_pool for group in groups_in_wave],
        "cpu_threads": int(cpu_threads),
        "gpu_devices": int(gpu_devices),
    }


def _stage_job_metadata(
    cfg: Config,
    groups_in_wave: list[PlannedPluginGroup],
    *,
    stage_index: int,
    worker_pool: str,
) -> dict[str, Any]:
    matching = [
        g for g in groups_in_wave
        if g.specs and str(g.specs[0].worker_pool).strip().lower() == worker_pool
    ]
    if not matching:
        raise ValueError(f"No groups found for worker_pool={worker_pool!r} in stage {stage_index}")

    cpu_threads = 0
    gpu_devices = 0
    group_ids: list[int] = []
    plugins: list[str] = []
    device_kinds: list[str] = []
    for group in matching:
        totals = group_resource_totals(cfg, list(group.specs))
        cpu_threads += int(totals["planned_cpu_threads"])
        gpu_devices += int(totals["planned_gpu_devices"])
        group_ids.append(int(group.group_id))
        plugins.extend(spec.name for spec in group.specs)
        for spec in group.specs:
            dk = str(spec.device_kind or "cpu").strip().lower()
            if dk not in device_kinds:
                device_kinds.append(dk)

    return {
        "job_id": f"stage{stage_index}-{worker_pool}",
        "stage": int(stage_index),
        "worker_pool": worker_pool,
        "resource_class": "gpu_enabled" if gpu_devices > 0 else "cpu_only",
        "device_kind": device_kinds[0] if len(device_kinds) == 1 else "mixed",
        "cpu_threads": int(cpu_threads),
        "gpu_devices": int(gpu_devices),
        "group_ids": sorted(group_ids),
        "plugins": plugins,
        "recommended_job": {
            "cpu_threads": int(cpu_threads),
            "gpu_devices": int(gpu_devices),
        },
    }


def _recommended_submission_mode(wave_entries: list[dict[str, Any]]) -> tuple[str, str]:
    has_gpu = any(int(entry.get("gpu_devices") or 0) > 0 for entry in wave_entries)
    if not has_gpu:
        return (
            "cpu_only",
            "No GPU-enabled plugin waves are present, so CPU-only scheduling is sufficient.",
        )
    if all(int(entry.get("gpu_devices") or 0) > 0 for entry in wave_entries):
        return (
            "single_job",
            "Every execution wave includes GPU work, so a single GPU-enabled job is the simplest fit.",
        )
    return (
        "split_by_stage",
        "CPU-only and GPU-enabled waves are both present, so staged submission can release GPU nodes during CPU-only phases.",
    )


def _submission_plan_metadata(cfg: Config, planned_groups: list[PlannedPluginGroup]) -> dict[str, Any]:
    all_waves = waves_from_groups(planned_groups)
    wave_entries = [
        _wave_resource_metadata(cfg, groups_in_wave, wave_index=wi)
        for wi, groups_in_wave in enumerate(all_waves)
    ]

    stages: list[dict[str, Any]] = []
    all_jobs: list[dict[str, Any]] = []
    for stage_index, groups_in_wave in enumerate(all_waves):
        worker_pools = sorted(
            {str(g.specs[0].worker_pool).strip().lower() for g in groups_in_wave if g.specs}
        )
        jobs = [
            _stage_job_metadata(cfg, groups_in_wave, stage_index=stage_index, worker_pool=wp)
            for wp in worker_pools
        ]
        all_jobs.extend(jobs)
        stages.append(
            {
                "stage": int(stage_index),
                "worker_pools": [job["worker_pool"] for job in jobs],
                "cpu_threads": sum(int(job["cpu_threads"]) for job in jobs),
                "gpu_devices": sum(int(job["gpu_devices"]) for job in jobs),
                "jobs": jobs,
            }
        )

    job_classes: dict[str, dict[str, Any]] = {}
    for job in all_jobs:
        wp = str(job["worker_pool"])
        current = job_classes.setdefault(
            wp,
            {
                "worker_pool": wp,
                "resource_class": job["resource_class"],
                "device_kind": str(job["device_kind"]),
                "peak_cpu_threads": 0,
                "peak_gpu_devices": 0,
                "stages": [],
            },
        )
        current["peak_cpu_threads"] = max(int(current["peak_cpu_threads"]), int(job["cpu_threads"]))
        current["peak_gpu_devices"] = max(int(current["peak_gpu_devices"]), int(job["gpu_devices"]))
        if int(job["stage"]) not in current["stages"]:
            current["stages"].append(int(job["stage"]))

    recommended_mode, reason = _recommended_submission_mode(wave_entries)
    return {
        "recommended_mode": recommended_mode,
        "reason": reason,
        "stages": stages,
        "job_classes": [
            {
                **entry,
                "stages": sorted(int(s) for s in entry["stages"]),
                "recommended_job": {
                    "cpu_threads": int(entry["peak_cpu_threads"]),
                    "gpu_devices": int(entry["peak_gpu_devices"]),
                },
            }
            for _, entry in sorted(job_classes.items())
        ],
    }


def scheduler_resource_metadata(cfg: Config, planned_groups: list[PlannedPluginGroup]) -> dict[str, Any]:
    wave_entries = [
        _wave_resource_metadata(cfg, groups_in_wave, wave_index=wi)
        for wi, groups_in_wave in enumerate(waves_from_groups(planned_groups))
    ]
    peak_cpu = max((int(e["cpu_threads"]) for e in wave_entries), default=0)
    peak_gpu = max((int(e["gpu_devices"]) for e in wave_entries), default=0)
    return {
        "single_job": {"cpu_threads": int(peak_cpu), "gpu_devices": int(peak_gpu)},
        "peak_cpu_threads": int(peak_cpu),
        "peak_gpu_devices": int(peak_gpu),
        "waves": wave_entries,
        "submission_plan": _submission_plan_metadata(cfg, planned_groups),
    }


def plugin_group_metadata(
    group: list[PluginExecutionSpec] | PlannedPluginGroup,
    *,
    cfg: Config | None = None,
) -> dict[str, Any]:
    if isinstance(group, PlannedPluginGroup):
        specs = list(group.specs)
        head = specs[0]
        metadata: dict[str, Any] = {
            "group_id": group.group_id,
            "depends_on_groups": list(group.depends_on_group_ids),
            "wave": group.wave,
        }
    else:
        specs = list(group)
        head = specs[0]
        metadata = {}
    metadata.update(
        {
            "plugins": [spec.name for spec in specs],
            "input_model": head.input_model,
            "execution_mode": head.execution_mode,
            "worker_pool": head.worker_pool,
            "device_kind": head.device_kind,
            "max_workers": head.max_workers,
            "cpu_threads_per_worker": group_cpu_threads_per_worker(specs),
            "gpu_devices_per_worker": group_gpu_devices_per_worker(specs),
        }
    )
    if cfg is not None:
        metadata.update(group_resource_totals(cfg, specs))
    return metadata


def plugin_metadata(spec: PluginExecutionSpec) -> dict[str, Any]:
    return {
        "input_model": spec.input_model,
        "execution_mode": spec.execution_mode,
        "worker_pool": spec.worker_pool,
        "device_kind": spec.device_kind,
        "max_workers": spec.max_workers,
        "cpu_threads_per_worker": int(spec.cpu_threads_per_worker),
        "gpu_devices_per_worker": int(spec.gpu_devices_per_worker),
        "requires": list(getattr(spec.plugin, "requires", [])),
        "failure_policy": spec.failure_policy,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def plugin_execution_metadata(cfg: Config, plugin_names: list[str] | None = None) -> dict[str, Any]:
    selected = list(plugin_names if plugin_names is not None else cfg.plugins)
    specs = resolve_plugin_specs(selected, cfg)
    planned_groups = plan_plugin_groups(specs)
    ordered_specs = [spec for group in planned_groups for spec in group.specs]
    wave_entries = [
        _wave_resource_metadata(cfg, groups_in_wave, wave_index=wi)
        for wi, groups_in_wave in enumerate(waves_from_groups(planned_groups))
    ]
    return {
        "groups": [plugin_group_metadata(group, cfg=cfg) for group in planned_groups],
        "waves": wave_entries,
        "scheduler_resources": scheduler_resource_metadata(cfg, planned_groups),
        "plugins": {spec.name: plugin_metadata(spec) for spec in ordered_specs},
        "runtime": {
            "cpu_workers": int(cfg.cpu_workers),
            "gpu_workers": int(cfg.gpu_workers),
            "gpu_devices": list(cfg.gpu_devices),
        },
    }
