"""Execute phase: run pdb_calculation plugins against prepared structures."""

from __future__ import annotations

import concurrent.futures
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any

import pandas as pd

from ..plugins import PLUGIN_REGISTRY
from ..plugins.base import Context
from ..runtime.workspace import (
    load_prepared_manifest as _load_prepared_manifest,
    plugin_bad_path as _plugin_bad_path,
    plugin_pdb_path as _plugin_pdb_path,
    plugin_status_path as _plugin_status_path,
    plugins_dir as _plugins_dir,
    prepared_dir as _prepared_dir,
    prepare_context as _prepare_context,
    run_unit as _run_unit,
)
from .config import Config
from .registry import instantiate_unit
from ..runtime._pool import process_or_thread_pool as _process_or_thread_pool
from ._schedule import (  # noqa: F401 — re-exported for backward compat
    PlannedPluginGroup,
    PluginExecutionSpec,
    group_gpu_devices_per_worker as _group_gpu_devices_per_worker,
    group_worker_budget as _group_worker_budget,
    plan_plugin_groups as _plan_plugin_groups,
    plan_plugin_waves as _plan_plugin_waves,
    plugin_execution_metadata,
    resolve_plugin_specs as _resolve_plugin_specs,
)

from .tables import (
    BAD_COLS,
    BufferedTableWriter,
    PDB_TABLE_NAME,
    STATUS_COLS,
    TABLE_SUFFIX,
    clear_table_artifacts as _clear_table_artifacts,
    count_pdb_rows as _count_pdb_rows,
    normalize_pdb_frame as _normalize_pdb_frame,
    read_frame as _read_frame,
    read_pdb_table as _read_pdb_table,
)

_LOG_LOCK = threading.Lock()
_WORKER_STATE = threading.local()


def _log(message: str) -> None:
    with _LOG_LOCK:
        print(message, flush=True)


def _log_plugin_preflight(specs: list[PluginExecutionSpec]) -> None:
    """Log availability of each plugin before processing begins.

    Calls available(None) which checks package imports without needing a
    structure, giving early feedback about missing optional dependencies.
    """
    for spec in specs:
        ok, reason = (
            spec.plugin.available(None)
            if hasattr(spec.plugin, "available")
            else (True, "")
        )
        if ok:
            _log(
                f"[plugin:{spec.name}] preflight ok "
                f"pool={spec.worker_pool} mode={spec.execution_mode}"
            )
        else:
            _log(f"[plugin:{spec.name}] WARN preflight_unavailable: {reason}")


# ---------------------------------------------------------------------------
# Progress helpers
# ---------------------------------------------------------------------------

def _progress_bar(done: int, total: int, *, width: int = 20) -> str:
    if total <= 0:
        return "[" + ("-" * width) + "]"
    filled = min(width, int(round(width * (float(done) / float(total)))))
    return "[" + ("#" * filled) + ("-" * max(0, width - filled)) + "]"


def _status_count_string(counts: dict[str, int]) -> str:
    ordered = []
    for key in ("ok", "failed", "failed_prepare", "skipped_preflight"):
        value = int(counts.get(key, 0))
        if value > 0:
            ordered.append(f"{key}={value}")
    return " ".join(ordered) if ordered else "no_status"


def _plugin_progress_line(
    spec: PluginExecutionSpec,
    *,
    done: int,
    total: int,
    rows: int,
    status_counts: dict[str, int],
) -> str:
    return (
        f"[plugin:{spec.name}] {_progress_bar(done, total)} {done}/{total} "
        f"rows={rows} {_status_count_string(status_counts)}"
    )


def _should_log_progress(
    *,
    done: int,
    total: int,
    cadence: int,
    last_logged_done: int,
    status_key: str | None = None,
) -> bool:
    if done <= 0 or done >= total:
        return True
    if status_key is not None and status_key != "ok":
        return True
    return (done - last_logged_done) >= max(int(cadence), 1)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class PluginRunState:
    spec: PluginExecutionSpec
    root: Path
    processed: set[str]
    counts: dict[str, int]
    pdb_writer: BufferedTableWriter
    status_writer: BufferedTableWriter
    bad_writer: BufferedTableWriter
    warned_statuses: set[str] = field(default_factory=set)

    @classmethod
    def from_out_dir(
        cls,
        out_dir: Path,
        spec: PluginExecutionSpec,
        checkpoint_enabled: bool,
        *,
        flush_interval: int,
    ) -> "PluginRunState":
        plugins_dir = _plugins_dir(out_dir)
        processed: set[str] = set()
        status_path = _plugin_status_path(out_dir, spec.name)
        bad_path = _plugin_bad_path(out_dir, spec.name)
        pdb_path = _plugin_pdb_path(out_dir, spec.name)

        if checkpoint_enabled and plugins_dir.exists():
            status_frame = _read_frame(status_path, STATUS_COLS)
            if not status_frame.empty:
                processed = set(status_frame["path"].tolist())
            counts = {PDB_TABLE_NAME: len(_read_pdb_table(pdb_path))}
            counts["status"] = len(status_frame)
            counts["bad"] = len(_read_frame(bad_path, BAD_COLS))
        else:
            plugins_dir.mkdir(parents=True, exist_ok=True)
            for path in (status_path, bad_path, pdb_path):
                _clear_table_artifacts(path)
            counts = {PDB_TABLE_NAME: 0, "status": 0, "bad": 0}

        return cls(
            spec=spec,
            root=plugins_dir,
            processed=processed,
            counts=counts,
            pdb_writer=BufferedTableWriter(
                pdb_path,
                flush_interval=flush_interval,
                normalize_frame=_normalize_pdb_frame,
            ),
            status_writer=BufferedTableWriter(
                status_path,
                flush_interval=flush_interval,
                columns=STATUS_COLS,
            ),
            bad_writer=BufferedTableWriter(
                bad_path,
                flush_interval=flush_interval,
                columns=BAD_COLS,
            ),
        )

    def record_result(
        self,
        pdb_rows: list[dict[str, Any]],
        status_rows: list[dict[str, Any]],
        bad_rows: list[dict[str, Any]],
    ) -> None:
        if pdb_rows:
            self.pdb_writer.append_rows(pdb_rows)
            self.counts[PDB_TABLE_NAME] += len(pdb_rows)
        self.status_writer.append_rows(status_rows)
        self.counts["status"] += len(status_rows)
        self.bad_writer.append_rows(bad_rows)
        self.counts["bad"] += len(bad_rows)

    def finalize_outputs(self) -> None:
        self.pdb_writer.materialize(skip_empty=True)
        self.status_writer.materialize(skip_empty=True)
        self.bad_writer.materialize(skip_empty=True)

    def mark_bad(self, source_path: Path, exc: Exception) -> None:
        self.mark_bad_message(
            source_path,
            error_type=type(exc).__name__,
            message=str(exc),
        )

    def mark_bad_message(self, source_path: Path, *, error_type: str, message: str) -> None:
        self.record_result(
            [],
            [],
            [{"path": str(source_path.resolve()), "error": f"{error_type}: {message}"}],
        )
        self.processed.add(str(source_path))

    @property
    def pdb_path(self) -> Path:
        return self.root / f"{self.spec.name}.pdb{TABLE_SUFFIX}"

    @property
    def status_path(self) -> Path:
        return self.root / f"{self.spec.name}.plugin_status{TABLE_SUFFIX}"

    @property
    def bad_path(self) -> Path:
        return self.root / f"{self.spec.name}.bad_files{TABLE_SUFFIX}"


# ---------------------------------------------------------------------------
# Context cache
# ---------------------------------------------------------------------------

class _LoadedContextCache:
    def __init__(self) -> None:
        self._templates: dict[tuple[str, str], Context] = {}
        self._failures: dict[tuple[str, str], Exception] = {}
        self._lock = threading.Lock()

    def get(self, source_path: Path, prepared_path: Path, cfg: Config) -> Context:
        key = (str(source_path.resolve()), str(prepared_path.resolve()))
        with self._lock:
            if key in self._failures:
                raise self._failures[key]
            template = self._templates.get(key)
        if template is None:
            try:
                loaded = _prepare_context(source_path, prepared_path, cfg)
            except Exception as exc:
                with self._lock:
                    self._failures[key] = exc
                raise
            with self._lock:
                self._templates.setdefault(key, loaded)
                template = self._templates[key]
        return self._clone(template)

    def _clone(self, template: Context) -> Context:
        clone = Context(
            path=template.path,
            assembly_id=template.assembly_id,
            aa=template.aa.copy(),
            role_map={name: tuple(chain_ids) for name, chain_ids in template.role_map.items()},
            config=template.config,
            metadata=deepcopy(template.metadata),
        )
        clone.rebuild_views()
        return clone


# ---------------------------------------------------------------------------
# Device helpers
# ---------------------------------------------------------------------------

def _normalize_gpu_device_label(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized.isdigit():
        return f"cuda:{normalized}"
    return normalized


def _group_device_slots(cfg: Config, group: list[PluginExecutionSpec], workers: int) -> list[str | None]:
    if not group or group[0].worker_pool != "gpu":
        return [None] * max(1, workers)
    normalized_devices = [
        _normalize_gpu_device_label(value)
        for value in list(cfg.gpu_devices)
    ]
    devices = [value for value in normalized_devices if value]
    if not devices:
        return [None] * max(1, workers)
    return devices[: max(1, workers)]


# ---------------------------------------------------------------------------
# Worker initialisation (runs inside subprocess/thread)
# ---------------------------------------------------------------------------

def _init_group_worker(config_data: dict[str, Any], device_override: str | None = None) -> None:
    _WORKER_STATE.cfg = Config(**dict(config_data))
    _WORKER_STATE.device_override = _normalize_gpu_device_label(device_override)


def _worker_base_config() -> Config:
    cfg = getattr(_WORKER_STATE, "cfg", None)
    if cfg is None:
        raise RuntimeError("plugin worker config was not initialized")
    return cfg


def _worker_device_override() -> str | None:
    return getattr(_WORKER_STATE, "device_override", None)


def _worker_config_for_plugins(plugin_names: list[str]) -> Config:
    cfg = _worker_base_config()
    device_override = _worker_device_override()
    if not device_override:
        return cfg

    plugin_params = {name: dict(params) for name, params in getattr(cfg, "plugin_params", {}).items()}
    changed = False
    for plugin_name in plugin_names:
        if plugin_name not in PLUGIN_REGISTRY:
            continue
        plugin = instantiate_unit(PLUGIN_REGISTRY[plugin_name])
        scheduling = plugin.scheduling(cfg) if hasattr(plugin, "scheduling") else {}
        worker_pool = str(scheduling.get("worker_pool") or getattr(plugin, "worker_pool", "cpu")).strip().lower()
        if worker_pool != "gpu":
            continue
        params = dict(plugin_params.get(plugin_name, {}))
        requested_device = str(params.get("device", "auto") or "auto").strip().lower()
        if requested_device in {"auto", "cuda"} or requested_device.isdigit():
            params["device"] = device_override
            plugin_params[plugin_name] = params
            changed = True
    if not changed:
        return cfg
    return cfg.model_copy(update={"plugin_params": plugin_params})


# ---------------------------------------------------------------------------
# Task execution (runs in worker)
# ---------------------------------------------------------------------------

def _execute_plugin_task(task: dict[str, Any]) -> dict[str, Any]:
    plugin_names = [str(name) for name in task.get("plugin_names", [])]
    source_path = Path(str(task["source_path"]))
    prepared_path = Path(str(task["prepared_path"]))
    cfg = _worker_config_for_plugins(plugin_names)
    try:
        ctx = _prepare_context(source_path, prepared_path, cfg)
    except Exception as exc:
        return {
            "source_path": str(source_path),
            "plugin_names": plugin_names,
            "prepare_error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }

    results: list[dict[str, Any]] = []
    for plugin_name in plugin_names:
        plugin = instantiate_unit(PLUGIN_REGISTRY[plugin_name])
        local_rows: list[dict[str, Any]] = []
        local_status: list[dict[str, Any]] = []
        ok = _run_unit(ctx, plugin, local_rows, local_status)
        results.append(
            {
                "plugin": plugin_name,
                "pdb_rows": local_rows,
                "status_rows": local_status,
                "bad_rows": [],
                "ok": bool(ok),
            }
        )
    return {
        "source_path": str(source_path),
        "plugin_names": plugin_names,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Dispatchers
# ---------------------------------------------------------------------------

def _submit_tasks_bounded(
    executor: concurrent.futures.Executor,
    task_records: list[dict[str, Any]],
    *,
    max_in_flight: int,
):
    pending: dict[concurrent.futures.Future, None] = {}
    next_index = 0

    while next_index < len(task_records) and len(pending) < max_in_flight:
        future = executor.submit(_execute_plugin_task, task_records[next_index])
        pending[future] = None
        next_index += 1

    while pending:
        done, _ = concurrent.futures.wait(
            set(pending),
            return_when=concurrent.futures.FIRST_COMPLETED,
        )
        for future in done:
            pending.pop(future, None)
            yield future.result()
            if next_index < len(task_records):
                new_future = executor.submit(_execute_plugin_task, task_records[next_index])
                pending[new_future] = None
                next_index += 1


def _run_group_tasks_shared_pool(
    task_records: list[dict[str, Any]],
    *,
    max_workers: int,
    config_data: dict[str, Any],
):
    with _process_or_thread_pool(
        max_workers=max_workers,
        initializer=_init_group_worker,
        initargs=(config_data, None),
    ) as executor:
        yield from _submit_tasks_bounded(executor, task_records, max_in_flight=max_workers)


def _run_group_tasks_device_slots(
    task_records: list[dict[str, Any]],
    *,
    device_slots: list[str | None],
    config_data: dict[str, Any],
):
    with ExitStack() as stack:
        try:
            executors = [
                stack.enter_context(
                    _process_or_thread_pool(
                        max_workers=1,
                        initializer=_init_group_worker,
                        initargs=(config_data, device_override),
                    )
                )
                for device_override in device_slots
            ]
        except PermissionError:
            executors = [
                stack.enter_context(
                    concurrent.futures.ThreadPoolExecutor(
                        max_workers=1,
                        initializer=_init_group_worker,
                        initargs=(config_data, device_override),
                    )
                )
                for device_override in device_slots
            ]
        yield from _drain_device_slot_tasks(executors, task_records)


def _drain_device_slot_tasks(
    executors: list[concurrent.futures.Executor],
    task_records: list[dict[str, Any]],
):
    pending: dict[concurrent.futures.Future, int] = {}
    next_index = 0

    for slot_index, executor in enumerate(executors):
        if next_index >= len(task_records):
            break
        future = executor.submit(_execute_plugin_task, task_records[next_index])
        pending[future] = slot_index
        next_index += 1

    while pending:
        done, _ = concurrent.futures.wait(
            set(pending),
            return_when=concurrent.futures.FIRST_COMPLETED,
        )
        for future in done:
            slot_index = pending.pop(future)
            yield future.result()
            if next_index < len(task_records):
                new_future = executors[slot_index].submit(_execute_plugin_task, task_records[next_index])
                pending[new_future] = slot_index
                next_index += 1


# ---------------------------------------------------------------------------
# Result recording
# ---------------------------------------------------------------------------

def _record_prepare_failure(
    source_path: Path,
    pending_specs: list[PluginExecutionSpec],
    *,
    error_type: str,
    message: str,
    states: dict[str, PluginRunState],
    group_progress: dict[str, int],
    group_targets: dict[str, int],
    group_status_counts: dict[str, dict[str, int]],
    group_last_logged: dict[str, int],
    progress_cadence: int,
) -> None:
    for spec in pending_specs:
        states[spec.name].mark_bad_message(source_path, error_type=error_type, message=message)
        group_progress[spec.name] += 1
        counts = group_status_counts[spec.name]
        counts["failed_prepare"] = int(counts.get("failed_prepare", 0)) + 1
        if _should_log_progress(
            done=group_progress[spec.name],
            total=int(group_targets[spec.name]),
            cadence=progress_cadence,
            last_logged_done=group_last_logged[spec.name],
            status_key="failed_prepare",
        ):
            _log(
                _plugin_progress_line(
                    spec,
                    done=group_progress[spec.name],
                    total=int(group_targets[spec.name]),
                    rows=states[spec.name].counts.get(PDB_TABLE_NAME, 0),
                    status_counts=counts,
                )
            )
            group_last_logged[spec.name] = group_progress[spec.name]


def _record_plugin_result(
    source_path: Path,
    spec: PluginExecutionSpec,
    result: dict[str, Any],
    *,
    states: dict[str, PluginRunState],
    group_progress: dict[str, int],
    group_targets: dict[str, int],
    group_status_counts: dict[str, dict[str, int]],
    group_last_logged: dict[str, int],
    progress_cadence: int,
) -> None:
    local_rows = list(result.get("pdb_rows", []))
    local_status = list(result.get("status_rows", []))
    local_bad = list(result.get("bad_rows", []))
    ok = bool(result.get("ok", False))
    states[spec.name].record_result(local_rows, local_status, local_bad)
    states[spec.name].processed.add(str(source_path))
    group_progress[spec.name] += 1
    counts = group_status_counts[spec.name]
    status = "unknown"
    if local_status:
        status = str(local_status[-1].get("status", "unknown"))
    counts[status] = int(counts.get(status, 0)) + 1
    if status in ("skipped_preflight", "failed"):
        state = states[spec.name]
        if status not in state.warned_statuses:
            msg = str(local_status[-1].get("message", "")) if local_status else ""
            _log(f"[plugin:{spec.name}] WARN first_{status} ({source_path.name}): {msg}")
            state.warned_statuses.add(status)
    if _should_log_progress(
        done=group_progress[spec.name],
        total=int(group_targets[spec.name]),
        cadence=progress_cadence,
        last_logged_done=group_last_logged[spec.name],
        status_key=status,
    ):
        _log(
            _plugin_progress_line(
                spec,
                done=group_progress[spec.name],
                total=int(group_targets[spec.name]),
                rows=states[spec.name].counts.get(PDB_TABLE_NAME, 0),
                status_counts=counts,
            )
        )
        group_last_logged[spec.name] = group_progress[spec.name]
    if not ok and spec.failure_policy == "raise":
        raise RuntimeError(f"Plugin {spec.name} failed for {source_path}")


# ---------------------------------------------------------------------------
# Group runners
# ---------------------------------------------------------------------------

def _log_group_summary(group: list[PluginExecutionSpec], states: dict[str, PluginRunState]) -> None:
    for spec in group:
        state = states[spec.name]
        _log(
            f"[plugin:{spec.name}] summary rows={state.counts.get(PDB_TABLE_NAME, 0)} "
            f"status={state.counts.get('status', 0)} bad={state.counts.get('bad', 0)}"
        )


def _log_group_start(
    cfg: Config,
    manifest: pd.DataFrame,
    group: list[PluginExecutionSpec],
    states: dict[str, PluginRunState],
) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, int]], dict[str, int], int]:
    if not group:
        return {}, {}, {}, {}, max(1, int(cfg.checkpoint_interval))

    from ._schedule import plugin_group_metadata as _plugin_group_metadata

    total_structures = int(len(manifest))
    total_pending = sum(
        1
        for row in manifest.itertuples(index=False)
        if any(str(getattr(row, "path")) not in states[spec.name].processed for spec in group)
    )
    plugins_label = ",".join(spec.name for spec in group)
    group_meta = _plugin_group_metadata(group)
    _log(
        "[execute] "
        f"pool={group_meta['worker_pool']} "
        f"device={group_meta['device_kind']} "
        f"mode={group_meta['execution_mode']} "
        f"plugin={plugins_label} pending={total_pending}/{total_structures}"
    )

    group_targets = {
        spec.name: sum(
            1
            for row in manifest.itertuples(index=False)
            if str(getattr(row, "path")) not in states[spec.name].processed
        )
        for spec in group
    }
    group_progress = {spec.name: 0 for spec in group}
    group_last_logged = {spec.name: 0 for spec in group}
    group_status_counts = {spec.name: {} for spec in group}
    progress_cadence = max(1, int(cfg.checkpoint_interval))
    workers = _group_worker_budget(cfg, group)
    if workers > 1:
        _log(f"[execute] dispatch workers={workers}")
        if group_meta["worker_pool"] == "gpu":
            device_slots = _group_device_slots(cfg, group, workers)
            if any(device_slots):
                _log(f"[execute] gpu_slots={','.join(str(slot) for slot in device_slots if slot)}")
            else:
                _log("[execute] gpu_slots=unassigned")

    for spec in group:
        total = int(group_targets[spec.name])
        if total > 0:
            _log(
                _plugin_progress_line(
                    spec,
                    done=0,
                    total=total,
                    rows=states[spec.name].counts.get(PDB_TABLE_NAME, 0),
                    status_counts={},
                )
            )
    return group_targets, group_progress, group_status_counts, group_last_logged, progress_cadence


def _group_task_records(
    manifest: pd.DataFrame,
    group: list[PluginExecutionSpec],
    states: dict[str, PluginRunState],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for row in manifest.itertuples(index=False):
        source_path = Path(row.path)
        pending_specs = [spec for spec in group if str(source_path) not in states[spec.name].processed]
        if not pending_specs:
            continue
        tasks.append(
            {
                "source_path": str(source_path),
                "prepared_path": str(Path(row.prepared_path)),
                "plugin_names": [spec.name for spec in pending_specs],
            }
        )
    return tasks


def _execute_plugin_group_serial(
    cfg: Config,
    manifest: pd.DataFrame,
    group: list[PluginExecutionSpec],
    states: dict[str, PluginRunState],
    context_cache: _LoadedContextCache,
) -> None:
    if not group:
        return
    (
        group_targets,
        group_progress,
        group_status_counts,
        group_last_logged,
        progress_cadence,
    ) = _log_group_start(cfg, manifest, group, states)

    for row in manifest.itertuples(index=False):
        source_path = Path(row.path)
        pending_specs = [spec for spec in group if str(source_path) not in states[spec.name].processed]
        if not pending_specs:
            continue

        prepared_path = Path(row.prepared_path)
        try:
            ctx = context_cache.get(source_path, prepared_path, cfg)
        except Exception as exc:
            _record_prepare_failure(
                source_path,
                pending_specs,
                error_type=type(exc).__name__,
                message=str(exc),
                states=states,
                group_progress=group_progress,
                group_targets=group_targets,
                group_status_counts=group_status_counts,
                group_last_logged=group_last_logged,
                progress_cadence=progress_cadence,
            )
            continue

        for spec in pending_specs:
            local_rows: list[dict[str, Any]] = []
            local_status: list[dict[str, Any]] = []
            local_bad: list[dict[str, Any]] = []
            ok = _run_unit(ctx, spec.plugin, local_rows, local_status)
            _record_plugin_result(
                source_path,
                spec,
                {
                    "pdb_rows": local_rows,
                    "status_rows": local_status,
                    "bad_rows": local_bad,
                    "ok": ok,
                },
                states=states,
                group_progress=group_progress,
                group_targets=group_targets,
                group_status_counts=group_status_counts,
                group_last_logged=group_last_logged,
                progress_cadence=progress_cadence,
            )

    _log_group_summary(group, states)


def _execute_plugin_group_parallel(
    cfg: Config,
    manifest: pd.DataFrame,
    group: list[PluginExecutionSpec],
    states: dict[str, PluginRunState],
) -> None:
    if not group:
        return
    (
        group_targets,
        group_progress,
        group_status_counts,
        group_last_logged,
        progress_cadence,
    ) = _log_group_start(cfg, manifest, group, states)
    task_records = _group_task_records(manifest, group, states)
    if not task_records:
        _log_group_summary(group, states)
        return

    spec_by_name = {spec.name: spec for spec in group}
    workers = _group_worker_budget(cfg, group)
    config_data = cfg.model_dump(mode="json")

    if group[0].worker_pool == "gpu":
        task_results = _run_group_tasks_device_slots(
            task_records,
            device_slots=_group_device_slots(cfg, group, workers),
            config_data=config_data,
        )
    else:
        task_results = _run_group_tasks_shared_pool(
            task_records,
            max_workers=workers,
            config_data=config_data,
        )

    for result in task_results:
        source_path = Path(str(result["source_path"]))
        if "prepare_error" in result:
            error = dict(result["prepare_error"])
            pending_specs = [spec_by_name[name] for name in result.get("plugin_names", []) if name in spec_by_name]
            _record_prepare_failure(
                source_path,
                pending_specs,
                error_type=str(error.get("type", "RuntimeError")),
                message=str(error.get("message", "")),
                states=states,
                group_progress=group_progress,
                group_targets=group_targets,
                group_status_counts=group_status_counts,
                group_last_logged=group_last_logged,
                progress_cadence=progress_cadence,
            )
            continue

        for plugin_result in result.get("results", []):
            plugin_name = str(plugin_result.get("plugin", ""))
            if plugin_name not in spec_by_name:
                continue
            _record_plugin_result(
                source_path,
                spec_by_name[plugin_name],
                plugin_result,
                states=states,
                group_progress=group_progress,
                group_targets=group_targets,
                group_status_counts=group_status_counts,
                group_last_logged=group_last_logged,
                progress_cadence=progress_cadence,
            )

    _log_group_summary(group, states)


def _execute_plugin_group(
    cfg: Config,
    manifest: pd.DataFrame,
    group: list[PluginExecutionSpec],
    states: dict[str, PluginRunState],
    context_cache: _LoadedContextCache,
) -> None:
    if _group_worker_budget(cfg, group) <= 1:
        _execute_plugin_group_serial(cfg, manifest, group, states, context_cache)
        return
    _execute_plugin_group_parallel(cfg, manifest, group, states)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_plugin(cfg: Config, plugin_name: str) -> dict[str, int]:
    """Run a single plugin against prepared structures."""
    return run_plugins(cfg, [plugin_name])


def run_plugins(cfg: Config, plugin_names: list[str]) -> dict[str, int]:
    """Run multiple plugins against prepared structures."""
    specs = _resolve_plugin_specs(plugin_names, cfg)
    _log_plugin_preflight(specs)

    out_dir = Path(cfg.out_dir).resolve()
    manifest = _load_prepared_manifest(out_dir)
    states = {
        spec.name: PluginRunState.from_out_dir(
            out_dir,
            spec,
            cfg.checkpoint_enabled,
            flush_interval=cfg.checkpoint_interval,
        )
        for spec in specs
    }
    waves = _plan_plugin_waves(specs)
    context_cache = _LoadedContextCache()

    for wave_index, wave in enumerate(waves):
        if not wave:
            continue
        if len(wave) > 1:
            wave_groups = ",".join(str(group.group_id) for group in wave)
            wave_pools = ",".join(group.specs[0].worker_pool for group in wave)
            _log(f"[execute] wave={wave_index} groups={wave_groups} pools={wave_pools}")
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(wave)) as executor:
                futures = [
                    executor.submit(_execute_plugin_group, cfg, manifest, list(group.specs), states, context_cache)
                    for group in wave
                ]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
            continue

        group = wave[0]
        _execute_plugin_group(cfg, manifest, list(group.specs), states, context_cache)

    for state in states.values():
        state.finalize_outputs()

    total_counts = {PDB_TABLE_NAME: 0, "status": 0, "bad": 0}
    for state in states.values():
        for key, value in state.counts.items():
            total_counts[key] += value

    prepared_dir = _prepared_dir(out_dir)
    prepared_frame = _read_pdb_table(prepared_dir / f"{PDB_TABLE_NAME}{TABLE_SUFFIX}")
    total_counts[PDB_TABLE_NAME] = max(total_counts[PDB_TABLE_NAME], len(prepared_frame))
    total_counts.update({key: value for key, value in _count_pdb_rows(prepared_frame).items() if key != PDB_TABLE_NAME})
    return total_counts
