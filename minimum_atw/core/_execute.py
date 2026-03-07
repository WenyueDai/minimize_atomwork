"""Execute phase: run pdb_calculation plugins against prepared structures."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
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


@dataclass(frozen=True)
class PluginExecutionSpec:
    name: str
    plugin: Any
    resource_class: str
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


def _plugin_execution_spec(plugin_name: str) -> PluginExecutionSpec:
    if plugin_name not in PLUGIN_REGISTRY:
        raise KeyError(f"Unknown plugin: {plugin_name}")
    plugin = instantiate_unit(PLUGIN_REGISTRY[plugin_name])
    return PluginExecutionSpec(
        name=plugin_name,
        plugin=plugin,
        resource_class=str(getattr(plugin, "resource_class", "lightweight") or "lightweight"),
        execution_mode=str(getattr(plugin, "execution_mode", "batched") or "batched"),
        failure_policy=str(getattr(plugin, "failure_policy", "continue") or "continue"),
    )


def _resolve_plugin_specs(plugin_names: list[str]) -> list[PluginExecutionSpec]:
    return [_plugin_execution_spec(plugin_name) for plugin_name in plugin_names]


def _plan_plugin_execution(specs: list[PluginExecutionSpec]) -> list[list[PluginExecutionSpec]]:
    lightweight_specs: list[PluginExecutionSpec] = []
    isolated_specs: list[PluginExecutionSpec] = []

    for spec in specs:
        if spec.execution_mode == "batched" and spec.resource_class == "lightweight":
            lightweight_specs.append(spec)
        else:
            isolated_specs.append(spec)

    plan: list[list[PluginExecutionSpec]] = []
    if lightweight_specs:
        plan.append(lightweight_specs)
    for spec in isolated_specs:
        plan.append([spec])
    return plan


def plugin_execution_metadata(plugin_names: list[str]) -> dict[str, Any]:
    specs = _resolve_plugin_specs(plugin_names)
    groups = _plan_plugin_execution(specs)
    return {
        "plugins": {
            spec.name: {
                "resource_class": spec.resource_class,
                "execution_mode": spec.execution_mode,
                "failure_policy": spec.failure_policy,
            }
            for spec in specs
        },
        "groups": [
            {
                "plugins": [spec.name for spec in group],
                "resource_class": "mixed" if len({spec.resource_class for spec in group}) > 1 else group[0].resource_class,
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

    if len(group) == 1:
        label = f"Running isolated plugin: {group[0].name}"
    else:
        label = f"Running batched plugins: {', '.join(spec.name for spec in group)}"
    print(label)

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
            continue

        for spec in pending_specs:
            local_rows: list[dict[str, Any]] = []
            local_status: list[dict[str, Any]] = []
            local_bad: list[dict[str, Any]] = []
            ok = _run_unit(ctx, spec.plugin, local_rows, local_status)
            states[spec.name].record_result(local_rows, local_status, local_bad)
            states[spec.name].processed.add(str(source_path))
            if not ok and spec.failure_policy == "raise":
                raise RuntimeError(f"Plugin {spec.name} failed for {source_path}")


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

    for group in _plan_plugin_execution(specs):
        _execute_plugin_group(cfg, manifest, group, states)

    total_counts = {PDB_TABLE_NAME: 0, "status": 0, "bad": 0}
    for state in states.values():
        for key, value in state.counts.items():
            total_counts[key] += value

    prepared_dir = _prepared_dir(out_dir)
    prepared_frame = _read_pdb_table(prepared_dir / f"{PDB_TABLE_NAME}{TABLE_SUFFIX}")
    total_counts[PDB_TABLE_NAME] = max(total_counts[PDB_TABLE_NAME], len(prepared_frame))
    total_counts.update({key: value for key, value in _count_pdb_rows(prepared_frame).items() if key != PDB_TABLE_NAME})
    return total_counts
