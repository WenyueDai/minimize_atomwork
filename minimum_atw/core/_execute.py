"""Execute phase: run pdb_calculation plugins against prepared structures."""

from __future__ import annotations
import concurrent.futures
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any

import pandas as pd

from ..plugins import PLUGIN_REGISTRY
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
    PDB_TABLE_NAME,
    STATUS_COLS,
    TABLE_SUFFIX,
    append_rows as _append_rows,
    count_pdb_rows as _count_pdb_rows,
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


@dataclass(frozen=True)
class PluginExecutionSpec:
    name: str
    plugin: Any
    input_model: str
    execution_mode: str
    failure_policy: str


@dataclass
class PluginRunState:
    spec: PluginExecutionSpec
    root: Path
    processed: set[str]
    counts: dict[str, int]

    @classmethod
    def from_out_dir(cls, out_dir: Path, spec: PluginExecutionSpec, checkpoint_enabled: bool) -> "PluginRunState":
        plugins_dir = _plugins_dir(out_dir)
        processed: set[str] = set()
        status_path = _plugin_status_path(out_dir, spec.name)
        bad_path = _plugin_bad_path(out_dir, spec.name)
        pdb_path = _plugin_pdb_path(out_dir, spec.name)

        if checkpoint_enabled and plugins_dir.exists():
            if status_path.exists():
                status_frame = pd.read_parquet(status_path)
                processed = set(status_frame["path"].tolist())
            counts = {PDB_TABLE_NAME: len(pd.read_parquet(pdb_path)) if pdb_path.exists() else 0}
            counts["status"] = len(pd.read_parquet(status_path)) if status_path.exists() else 0
            counts["bad"] = len(pd.read_parquet(bad_path)) if bad_path.exists() else 0
        else:
            plugins_dir.mkdir(parents=True, exist_ok=True)
            for path in (status_path, bad_path, pdb_path):
                if path.exists():
                    path.unlink()
            counts = {PDB_TABLE_NAME: 0, "status": 0, "bad": 0}

        return cls(spec=spec, root=plugins_dir, processed=processed, counts=counts)

    def record_result(
        self,
        pdb_rows: list[dict[str, Any]],
        status_rows: list[dict[str, Any]],
        bad_rows: list[dict[str, Any]],
    ) -> None:
        if pdb_rows:
            _append_rows(self.pdb_path, pdb_rows)
            self.counts[PDB_TABLE_NAME] += len(pdb_rows)
        _append_rows(self.status_path, status_rows, STATUS_COLS)
        self.counts["status"] += len(status_rows)
        _append_rows(self.bad_path, bad_rows, BAD_COLS)
        self.counts["bad"] += len(bad_rows)

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


def _resolve_input_model(plugin: Any) -> str:
    explicit = getattr(plugin, "input_model", None)
    if explicit:
        return str(explicit)

    # Compatibility fallback for older third-party plugins.
    resource_class = str(getattr(plugin, "resource_class", "lightweight") or "lightweight")
    if resource_class == "lightweight":
        return "atom_array"
    return "hybrid"


def _plugin_execution_spec(plugin_name: str) -> PluginExecutionSpec:
    if plugin_name not in PLUGIN_REGISTRY:
        raise KeyError(f"Unknown plugin: {plugin_name}")
    plugin = instantiate_unit(PLUGIN_REGISTRY[plugin_name])
    return PluginExecutionSpec(
        name=plugin_name,
        plugin=plugin,
        input_model=_resolve_input_model(plugin),
        execution_mode=str(getattr(plugin, "execution_mode", "batched") or "batched"),
        failure_policy=str(getattr(plugin, "failure_policy", "continue") or "continue"),
    )


def _resolve_plugin_specs(plugin_names: list[str]) -> list[PluginExecutionSpec]:
    return [_plugin_execution_spec(plugin_name) for plugin_name in plugin_names]


def _plan_plugin_execution(specs: list[PluginExecutionSpec]) -> list[list[PluginExecutionSpec]]:
    atom_array_specs: list[PluginExecutionSpec] = []
    isolated_specs: list[PluginExecutionSpec] = []

    for spec in specs:
        if spec.execution_mode == "batched" and spec.input_model == "atom_array":
            atom_array_specs.append(spec)
        else:
            isolated_specs.append(spec)

    plan: list[list[PluginExecutionSpec]] = []
    if atom_array_specs:
        plan.append(atom_array_specs)
    for spec in isolated_specs:
        plan.append([spec])
    return plan


def plugin_execution_metadata(plugin_names: list[str]) -> dict[str, Any]:
    specs = _resolve_plugin_specs(plugin_names)
    groups = _plan_plugin_execution(specs)
    return {
        "plugins": {
            spec.name: {
                "input_model": spec.input_model,
                "execution_mode": spec.execution_mode,
                "failure_policy": spec.failure_policy,
            }
            for spec in specs
        },
        "groups": [
            {
                "plugins": [spec.name for spec in group],
                "input_model": "mixed" if len({spec.input_model for spec in group}) > 1 else group[0].input_model,
                "execution_mode": "mixed" if len({spec.execution_mode for spec in group}) > 1 else group[0].execution_mode,
            }
            for group in groups
        ],
    }


def _execute_plugin_group(
    cfg: Config,
    manifest: pd.DataFrame,
    group: list[PluginExecutionSpec],
    states: dict[str, PluginRunState],
) -> None:
    if not group:
        return

    total_structures = int(len(manifest))
    total_pending = sum(
        1
        for row in manifest.itertuples(index=False)
        if any(str(getattr(row, "path")) not in states[spec.name].processed for spec in group)
    )
    if len(group) == 1:
        spec = group[0]
        label = (
            f"[execute] plugin={spec.name} mode=isolated input_model={spec.input_model} "
            f"pending={total_pending}/{total_structures}"
        )
    else:
        label = (
            f"[execute] batched plugins={','.join(spec.name for spec in group)} "
            f"input_model=atom_array pending={total_pending}/{total_structures}"
        )
    _log(label)

    group_targets = {
        spec.name: sum(
            1
            for row in manifest.itertuples(index=False)
            if str(getattr(row, "path")) not in states[spec.name].processed
        )
        for spec in group
    }
    group_progress = {spec.name: 0 for spec in group}
    group_status_counts = {spec.name: {} for spec in group}

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
            ctx = _prepare_context(source_path, prepared_path, cfg)
        except Exception as exc:
            for spec in pending_specs:
                states[spec.name].mark_bad(source_path, exc)
                group_progress[spec.name] += 1
                counts = group_status_counts[spec.name]
                counts["failed_prepare"] = int(counts.get("failed_prepare", 0)) + 1
                _log(
                    _plugin_progress_line(
                        spec,
                        done=group_progress[spec.name],
                        total=int(group_targets[spec.name]),
                        rows=states[spec.name].counts.get(PDB_TABLE_NAME, 0),
                        status_counts=counts,
                    )
                )
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
            _log(
                _plugin_progress_line(
                    spec,
                    done=group_progress[spec.name],
                    total=int(group_targets[spec.name]),
                    rows=states[spec.name].counts.get(PDB_TABLE_NAME, 0),
                    status_counts=counts,
                )
            )
            if not ok and spec.failure_policy == "raise":
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
    states = {
        spec.name: PluginRunState.from_out_dir(out_dir, spec, cfg.checkpoint_enabled)
        for spec in specs
    }
    groups = _plan_plugin_execution(specs)

    if len(groups) <= 1:
        for group in groups:
            _execute_plugin_group(cfg, manifest, group, states)
    else:
        max_workers = len(groups)
        _log(f"[execute] groups={len(groups)} workers={max_workers}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_execute_plugin_group, cfg, manifest, group, states)
                for group in groups
            ]
            for future in concurrent.futures.as_completed(futures):
                future.result()

    total_counts = {PDB_TABLE_NAME: 0, "status": 0, "bad": 0}
    for state in states.values():
        for key, value in state.counts.items():
            total_counts[key] += value

    prepared_dir = _prepared_dir(out_dir)
    prepared_frame = _read_pdb_table(prepared_dir / f"{PDB_TABLE_NAME}{TABLE_SUFFIX}")
    total_counts[PDB_TABLE_NAME] = max(total_counts[PDB_TABLE_NAME], len(prepared_frame))
    total_counts.update({key: value for key, value in _count_pdb_rows(prepared_frame).items() if key != PDB_TABLE_NAME})
    return total_counts
