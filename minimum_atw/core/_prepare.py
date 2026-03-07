"""Prepare phase: load, validate, manipulate, and cache structures."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
from biotite.structure.io import save_structure

from ..plugins.dataset.manipulation import DATASET_MANIPULATION_REGISTRY
from ..plugins.dataset.quality_control import DATASET_QUALITY_CONTROL_REGISTRY
from ..plugins.pdb.manipulation import PDB_MANIPULATION_REGISTRY
from ..plugins.pdb.quality_control import PDB_QUALITY_CONTROL_REGISTRY
from ..runtime.workspace import (
    base_rows_for_context as _base_rows_for_context,
    discover_inputs as _discover,
    prepare_context as _prepare_context,
    prepared_filename as _prepared_filename,
    prepared_manifest_path as _prepared_manifest_path,
    run_unit as _run_unit,
)
from .config import Config, PREPARE_SECTION_ORDER
from .registry import instantiate_unit
from .tables import (
    BAD_COLS,
    MANIFEST_COLS,
    PDB_KEY_COLS,
    PDB_TABLE_NAME,
    STATUS_COLS,
    TABLE_SUFFIX,
    append_rows as _append_rows,
    count_pdb_rows as _count_pdb_rows,
    read_frame as _read_frame,
    read_pdb_table as _read_pdb_table,
    rows_to_pdb_frame as _rows_to_pdb_frame,
    write_frame as _write_frame,
)


def _log(message: str) -> None:
    print(message, flush=True)


def _progress_bar(done: int, total: int, *, width: int = 20) -> str:
    if total <= 0:
        return "[" + ("-" * width) + "]"
    filled = min(width, int(round(width * (float(done) / float(total)))))
    return "[" + ("#" * filled) + ("-" * max(0, width - filled)) + "]"


def _status_count_string(counts: dict[str, int]) -> str:
    ordered = []
    for key in ("ok", "failed", "failed_load", "skipped_preflight", "skipped_checkpoint"):
        value = int(counts.get(key, 0))
        if value > 0:
            ordered.append(f"{key}={value}")
    return " ".join(ordered) if ordered else "no_status"


def _prepare_progress_line(unit_name: str, *, done: int, total: int, status_counts: dict[str, int]) -> str:
    return f"[prepare:{unit_name}] {_progress_bar(done, total)} {done}/{total} {_status_count_string(status_counts)}"


def _empty_pdb_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=PDB_KEY_COLS)


def _append_stage_outputs(
    out_dir: Path,
    pdb_frame: pd.DataFrame,
    status_rows: list[dict[str, Any]],
    bad_rows: list[dict[str, Any]],
) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)

    if not pdb_frame.empty:
        path = out_dir / f"{PDB_TABLE_NAME}{TABLE_SUFFIX}"
        if path.exists():
            existing = _read_pdb_table(path)
            combined = pd.concat([existing, pdb_frame], ignore_index=True, sort=False)
            combined = combined.drop_duplicates(subset=PDB_KEY_COLS)
        else:
            combined = pdb_frame
        combined.to_parquet(path, index=False)

    _append_rows(out_dir / f"plugin_status{TABLE_SUFFIX}", status_rows, STATUS_COLS)
    bad_path = out_dir / f"bad_files{TABLE_SUFFIX}"
    _append_rows(bad_path, bad_rows, BAD_COLS)

    final_pdb = _read_pdb_table(out_dir / f"{PDB_TABLE_NAME}{TABLE_SUFFIX}")
    final_status = _read_frame(out_dir / f"plugin_status{TABLE_SUFFIX}", STATUS_COLS)
    final_bad = _read_frame(bad_path, BAD_COLS)
    return {**_count_pdb_rows(final_pdb), "status": len(final_status), "bad": len(final_bad)}


def _prepare_counts_from_dir(prepared_dir: Path) -> dict[str, int]:
    counts = _count_pdb_rows(_read_pdb_table(prepared_dir / f"{PDB_TABLE_NAME}{TABLE_SUFFIX}"))
    counts["status"] = len(_read_frame(prepared_dir / f"plugin_status{TABLE_SUFFIX}", STATUS_COLS))
    counts["bad"] = len(_read_frame(prepared_dir / f"bad_files{TABLE_SUFFIX}", BAD_COLS))
    return counts


def _load_manifest_checkpoint_paths(manifest_ckpt: Path) -> set[str]:
    done_paths: set[str] = set()
    if not manifest_ckpt.exists():
        return done_paths
    with manifest_ckpt.open() as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            done_paths.add(row["path"])
    return done_paths


def _finalize_manifest_checkpoint(out_dir: Path, manifest_ckpt: Path) -> None:
    if not manifest_ckpt.exists():
        return
    records: list[dict[str, str]] = []
    with manifest_ckpt.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    _write_frame(_prepared_manifest_path(out_dir), records, MANIFEST_COLS)


def _prepared_manifest_entry(
    cfg: Config,
    source_path: Path,
    prepared_structures_dir: Path,
    *,
    ctx: Any,
) -> tuple[Path | None, dict[str, Any]]:
    prepared_path = prepared_structures_dir / _prepared_filename(source_path) if cfg.keep_prepared_structures else None
    source_meta = dict(getattr(ctx, "metadata", {}).get("source", {}))
    loaded_meta = dict(getattr(ctx, "metadata", {}).get("loaded", {}))
    structure_meta = dict(getattr(ctx, "metadata", {}).get("structure", {}))
    return prepared_path, {
        "path": str(source_meta.get("path", getattr(ctx, "path", str(source_path.resolve())))),
        "prepared_path": str(prepared_path.resolve()) if prepared_path else str(source_path.resolve()),
        "source_name": str(source_meta.get("name", source_path.name)),
        "source_format": str(source_meta.get("format", source_path.suffix.lower().lstrip("."))),
        "source_size_bytes": int(source_meta.get("size_bytes", source_path.stat().st_size)),
        "source_mtime_ns": int(source_meta.get("mtime_ns", source_path.stat().st_mtime_ns)),
        "loaded_path": str(loaded_meta.get("path", source_path.resolve())),
        "loaded_format": str(loaded_meta.get("format", source_path.suffix.lower().lstrip("."))),
        "n_atoms_loaded": int(structure_meta.get("n_atoms_loaded", 0) or 0),
        "n_chains_loaded": int(structure_meta.get("n_chains_loaded", 0) or 0),
    }


def _write_prepared_structure(prepared_path: Path | None, ctx: Any) -> None:
    if prepared_path is None:
        return
    prepared_path.parent.mkdir(parents=True, exist_ok=True)
    save_structure(prepared_path, ctx.aa)


def _rows_to_stage_frame(base_rows: list[dict[str, Any]], extra_rows: list[dict[str, Any]]) -> pd.DataFrame:
    rows = list(base_rows)
    rows.extend(extra_rows)
    return _rows_to_pdb_frame(rows)


def _prepare_units_by_section(cfg: Config) -> dict[str, list[Any]]:
    prepare_registry = dict(PDB_QUALITY_CONTROL_REGISTRY)
    for registry_name, registry in (
        ("pdb_manipulation", PDB_MANIPULATION_REGISTRY),
        ("dataset_quality_control", DATASET_QUALITY_CONTROL_REGISTRY),
        ("dataset_manipulation", DATASET_MANIPULATION_REGISTRY),
    ):
        overlap = set(prepare_registry) & set(registry)
        if overlap:
            raise ValueError(
                f"Duplicate prepare unit names across prepare registries (current={registry_name}): {sorted(overlap)}"
            )
        prepare_registry.update(registry)
    section_by_name = {
        name: str(getattr(unit, "prepare_section", "structure") or "structure")
        for name, unit in prepare_registry.items()
    }
    grouped_names = cfg.prepare_names_by_section(section_by_name=section_by_name)
    grouped_units: dict[str, list[Any]] = {section: [] for section in PREPARE_SECTION_ORDER}
    for section in PREPARE_SECTION_ORDER:
        for unit_name in grouped_names[section]:
            grouped_units[section].append(instantiate_unit(prepare_registry[unit_name]))
    return grouped_units


def _ordered_prepare_units(cfg: Config) -> list[Any]:
    grouped_units = _prepare_units_by_section(cfg)
    ordered: list[Any] = []
    for section in PREPARE_SECTION_ORDER:
        ordered.extend(grouped_units[section])
    return ordered


def prepare_execution_metadata(cfg: Config) -> dict[str, Any]:
    grouped_units = _prepare_units_by_section(cfg)
    return {
        "sections": {
            section: [unit.name for unit in grouped_units[section]]
            for section in PREPARE_SECTION_ORDER
        }
    }


def _prepare_outputs_checkpointed(
    cfg: Config,
    *,
    input_dir: Path,
    out_dir: Path,
    prepared_dir: Path,
    prepared_structures_dir: Path,
    manipulation_units: list[Any],
    manifest_ckpt: Path,
) -> dict[str, int]:
    done_paths = _load_manifest_checkpoint_paths(manifest_ckpt)
    discovered = _discover(input_dir)
    initial_done = int(len(done_paths))
    prepared_dir.mkdir(parents=True, exist_ok=True)
    if cfg.keep_prepared_structures:
        prepared_structures_dir.mkdir(parents=True, exist_ok=True)

    _log(
        f"[prepare] mode=checkpointed structures={len(discovered)} "
        f"units={','.join(unit.name for unit in manipulation_units) or 'none'}"
    )
    unit_progress = {unit.name: initial_done for unit in manipulation_units}
    unit_status_counts = {
        unit.name: ({"skipped_checkpoint": initial_done} if initial_done > 0 else {})
        for unit in manipulation_units
    }
    for unit in manipulation_units:
        _log(
            _prepare_progress_line(
                unit.name,
                done=unit_progress[unit.name],
                total=len(discovered),
                status_counts=unit_status_counts[unit.name],
            )
        )

    for source_path in discovered:
        src_str = str(source_path.resolve())
        if src_str in done_paths:
            continue

        try:
            ctx = _prepare_context(source_path, source_path, cfg)
        except Exception as exc:
            _append_stage_outputs(prepared_dir, _empty_pdb_frame(), [], [{"path": src_str, "error": f"{type(exc).__name__}: {exc}"}])
            for unit in manipulation_units:
                unit_progress[unit.name] += 1
                counts = unit_status_counts[unit.name]
                counts["failed_load"] = int(counts.get("failed_load", 0)) + 1
                _log(
                    _prepare_progress_line(
                        unit.name,
                        done=unit_progress[unit.name],
                        total=len(discovered),
                        status_counts=counts,
                    )
                )
            done_paths.add(src_str)
            continue

        manipulation_ok = True
        manipulation_rows: list[dict[str, Any]] = []
        status_rows: list[dict[str, Any]] = []
        bad_rows: list[dict[str, Any]] = []
        for unit in manipulation_units:
            manipulation_ok = _run_unit(ctx, unit, manipulation_rows, status_rows) and manipulation_ok
            unit_progress[unit.name] += 1
            status = status_rows[-1] if status_rows else {}
            counts = unit_status_counts[unit.name]
            key = str(status.get("status", "unknown"))
            counts[key] = int(counts.get(key, 0)) + 1
            _log(
                _prepare_progress_line(
                    unit.name,
                    done=unit_progress[unit.name],
                    total=len(discovered),
                    status_counts=counts,
                )
            )
        if not manipulation_ok:
            bad_rows.append({"path": ctx.path, "error": "prepare_failed"})
            _append_stage_outputs(prepared_dir, _empty_pdb_frame(), status_rows, bad_rows)
            done_paths.add(src_str)
            continue

        base_rows = _base_rows_for_context(ctx)
        prepared_path, manifest_entry = _prepared_manifest_entry(
            cfg,
            source_path,
            prepared_structures_dir,
            ctx=ctx,
        )
        with manifest_ckpt.open("a") as fh:
            fh.write(json.dumps(manifest_entry) + "\n")

        _write_prepared_structure(prepared_path, ctx)
        _append_stage_outputs(
            prepared_dir,
            _rows_to_stage_frame(base_rows, manipulation_rows),
            status_rows,
            bad_rows,
        )
        done_paths.add(src_str)

    _finalize_manifest_checkpoint(out_dir, manifest_ckpt)
    return _prepare_counts_from_dir(prepared_dir)


def prepare_outputs(cfg: Config) -> dict[str, int]:
    """Run the prepare phase: load, validate, manipulate, and cache all structures."""
    from ..runtime.workspace import (
        prepared_dir as _prepared_dir,
        prepared_structures_dir as _prepared_structures_dir,
        plugins_dir as _plugins_dir,
    )

    input_dir = Path(cfg.input_dir).resolve()
    out_dir = Path(cfg.out_dir).resolve()
    prepared_dir = _prepared_dir(out_dir)
    prepared_structures_dir = _prepared_structures_dir(out_dir)
    manipulation_units = _ordered_prepare_units(cfg)
    plugins_dir = _plugins_dir(out_dir)
    manifest_ckpt = prepared_dir / "manifest_checkpoint.jsonl"
    _log(
        f"[prepare] start input_dir={input_dir} out_dir={out_dir} "
        f"resume={cfg.checkpoint_enabled} keep_prepared={cfg.keep_prepared_structures}"
    )

    if not cfg.checkpoint_enabled:
        if prepared_dir.exists():
            shutil.rmtree(prepared_dir)
        if plugins_dir.exists():
            shutil.rmtree(plugins_dir)
    prepared_dir.mkdir(parents=True, exist_ok=True)
    plugins_dir.mkdir(parents=True, exist_ok=True)
    if cfg.keep_prepared_structures:
        prepared_structures_dir.mkdir(parents=True, exist_ok=True)

    counts = _prepare_outputs_checkpointed(
        cfg,
        input_dir=input_dir,
        out_dir=out_dir,
        prepared_dir=prepared_dir,
        prepared_structures_dir=prepared_structures_dir,
        manipulation_units=manipulation_units,
        manifest_ckpt=manifest_ckpt,
    )
    _log(f"[prepare] complete counts={counts}")
    return counts
