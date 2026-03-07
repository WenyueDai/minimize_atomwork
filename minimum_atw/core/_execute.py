"""Execute phase: run pdb_calculation plugins against prepared structures."""

from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
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

def _log(message: str) -> None:
    with _LOG_LOCK:
        print(message, flush=True)


_LOG_LOCK = threading.Lock()


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
    spec: "PluginExecutionSpec",
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


@dataclass(frozen=True)
class PluginExecutionSpec:
    name: str
    plugin: Any


@dataclass
class PluginRunState:
    spec: PluginExecutionSpec
    root: Path
    processed: set[str]
    counts: dict[str, int]
    pdb_writer: BufferedTableWriter
    status_writer: BufferedTableWriter
    bad_writer: BufferedTableWriter

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
        self.record_result(
            [],
            [],
            [{"path": str(source_path.resolve()), "error": f"{type(exc).__name__}: {exc}"}],
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


class _LoadedContextCache:
    def __init__(self) -> None:
        self._templates: dict[tuple[str, str], Context] = {}
        self._failures: dict[tuple[str, str], Exception] = {}

    def get(self, source_path: Path, prepared_path: Path, cfg: Config) -> Context:
        key = (str(source_path.resolve()), str(prepared_path.resolve()))
        if key in self._failures:
            raise self._failures[key]
        template = self._templates.get(key)
        if template is None:
            try:
                template = _prepare_context(source_path, prepared_path, cfg)
            except Exception as exc:
                self._failures[key] = exc
                raise
            self._templates[key] = template
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


def _plugin_execution_spec(plugin_name: str) -> PluginExecutionSpec:
    if plugin_name not in PLUGIN_REGISTRY:
        raise KeyError(f"Unknown plugin: {plugin_name}")
    return PluginExecutionSpec(name=plugin_name, plugin=instantiate_unit(PLUGIN_REGISTRY[plugin_name]))


def _resolve_plugin_specs(plugin_names: list[str]) -> list[PluginExecutionSpec]:
    return [_plugin_execution_spec(plugin_name) for plugin_name in plugin_names]


def _plan_plugin_execution(specs: list[PluginExecutionSpec]) -> list[list[PluginExecutionSpec]]:
    """Return specs in topological order (one per group), respecting 'requires' dependencies."""
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
        spec = spec_by_name[name]
        for req in getattr(spec.plugin, "requires", []):
            if req in spec_by_name:
                _visit(req, visiting)
        visited.add(name)
        order.append(spec)

    for spec in specs:
        _visit(spec.name, frozenset())

    return [[spec] for spec in order]


def plugin_execution_metadata(plugin_names: list[str]) -> dict[str, Any]:
    groups = _plan_plugin_execution(_resolve_plugin_specs(plugin_names))
    return {"plugins": [spec.name for group in groups for spec in group]}


def _execute_plugin_group(
    cfg: Config,
    manifest: pd.DataFrame,
    group: list[PluginExecutionSpec],
    states: dict[str, PluginRunState],
    context_cache: _LoadedContextCache,
) -> None:
    if not group:
        return

    total_structures = int(len(manifest))
    total_pending = sum(
        1
        for row in manifest.itertuples(index=False)
        if any(str(getattr(row, "path")) not in states[spec.name].processed for spec in group)
    )
    plugins_label = ",".join(spec.name for spec in group)
    _log(f"[execute] plugin={plugins_label} pending={total_pending}/{total_structures}")

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

    for row in manifest.itertuples(index=False):
        source_path = Path(row.path)
        pending_specs = [spec for spec in group if str(source_path) not in states[spec.name].processed]
        if not pending_specs:
            continue

        prepared_path = Path(row.prepared_path)
        try:
            ctx = context_cache.get(source_path, prepared_path, cfg)
        except Exception as exc:
            for spec in pending_specs:
                states[spec.name].mark_bad(source_path, exc)
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
            continue

        for spec in pending_specs:
            local_rows: list[dict[str, Any]] = []
            local_status: list[dict[str, Any]] = []
            local_bad: list[dict[str, Any]] = []
            ok = _run_unit(ctx, spec.plugin, local_rows, local_status)
            states[spec.name].record_result(local_rows, local_status, local_bad)
            states[spec.name].processed.add(str(source_path))
            group_progress[spec.name] += 1
            counts = group_status_counts[spec.name]
            status = "unknown"
            if local_status:
                status = str(local_status[-1].get("status", "unknown"))
            counts[status] = int(counts.get(status, 0)) + 1
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
            if not ok and getattr(spec.plugin, "failure_policy", "continue") == "raise":
                raise RuntimeError(f"Plugin {spec.name} failed for {source_path}")

    for spec in group:
        state = states[spec.name]
        _log(
            f"[plugin:{spec.name}] summary rows={state.counts.get(PDB_TABLE_NAME, 0)} "
            f"status={state.counts.get('status', 0)} bad={state.counts.get('bad', 0)}"
        )


def run_plugin(cfg: Config, plugin_name: str) -> dict[str, int]:
    """Run a single plugin against prepared structures."""
    return run_plugins(cfg, [plugin_name])


def run_plugins(cfg: Config, plugin_names: list[str]) -> dict[str, int]:
    """Run multiple plugins against prepared structures."""
    specs = _resolve_plugin_specs(plugin_names)

    out_dir = Path(cfg.out_dir).resolve()
    manifest = _load_prepared_manifest(out_dir)
    context_cache = _LoadedContextCache()
    states = {
        spec.name: PluginRunState.from_out_dir(
            out_dir,
            spec,
            cfg.checkpoint_enabled,
            flush_interval=cfg.checkpoint_interval,
        )
        for spec in specs
    }
    groups = _plan_plugin_execution(specs)

    for group in groups:
        _execute_plugin_group(cfg, manifest, group, states, context_cache)

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
