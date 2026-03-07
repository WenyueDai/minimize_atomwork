from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_PDB_OUTPUT_NAME = "pdb.parquet"
DEFAULT_DATASET_OUTPUT_NAME = "dataset.parquet"
RUN_METADATA_NAME = "run_metadata.json"
DATASET_METADATA_NAME = "dataset_metadata.json"
BAD_OUTPUT_NAME = "bad_files.parquet"
PLUGIN_STATUS_OUTPUT_NAME = "plugin_status.parquet"
RESERVED_OUTPUT_NAMES = {
    RUN_METADATA_NAME,
    DATASET_METADATA_NAME,
    BAD_OUTPUT_NAME,
    PLUGIN_STATUS_OUTPUT_NAME,
}


def normalize_output_filename(value: Any, *, default: str, label: str) -> str:
    normalized = str(value or "").strip() or default
    name = Path(normalized).name
    if name != normalized:
        raise ValueError(f"{label} must be a filename, not a path")
    if not name.endswith(".parquet"):
        name = f"{name}.parquet"
    if name in RESERVED_OUTPUT_NAMES:
        raise ValueError(f"{label} cannot use reserved output name '{name}'")
    return name


def read_output_metadata(out_dir: Path) -> dict[str, Any]:
    for filename in (RUN_METADATA_NAME, DATASET_METADATA_NAME):
        path = out_dir / filename
        if path.exists():
            return json.loads(path.read_text())
    return {}


def output_files_from_metadata(metadata: dict[str, Any] | None) -> dict[str, str]:
    metadata = metadata or {}
    output_files = metadata.get("output_files")
    if isinstance(output_files, dict):
        pdb_name = output_files.get("pdb", DEFAULT_PDB_OUTPUT_NAME)
        dataset_name = output_files.get("dataset", DEFAULT_DATASET_OUTPUT_NAME)
        return {
            "pdb": normalize_output_filename(pdb_name, default=DEFAULT_PDB_OUTPUT_NAME, label="output_files.pdb"),
            "dataset": normalize_output_filename(
                dataset_name,
                default=DEFAULT_DATASET_OUTPUT_NAME,
                label="output_files.dataset",
            ),
        }
    raw_config = metadata.get("config")
    if isinstance(raw_config, dict):
        return {
            "pdb": normalize_output_filename(
                raw_config.get("pdb_output_name"),
                default=DEFAULT_PDB_OUTPUT_NAME,
                label="pdb_output_name",
            ),
            "dataset": normalize_output_filename(
                raw_config.get("dataset_output_name"),
                default=DEFAULT_DATASET_OUTPUT_NAME,
                label="dataset_output_name",
            ),
        }
    return {"pdb": DEFAULT_PDB_OUTPUT_NAME, "dataset": DEFAULT_DATASET_OUTPUT_NAME}


def output_files_from_config(config: Any | None) -> dict[str, str]:
    if config is None:
        return {"pdb": DEFAULT_PDB_OUTPUT_NAME, "dataset": DEFAULT_DATASET_OUTPUT_NAME}
    return {
        "pdb": normalize_output_filename(
            getattr(config, "pdb_output_name", DEFAULT_PDB_OUTPUT_NAME),
            default=DEFAULT_PDB_OUTPUT_NAME,
            label="pdb_output_name",
        ),
        "dataset": normalize_output_filename(
            getattr(config, "dataset_output_name", DEFAULT_DATASET_OUTPUT_NAME),
            default=DEFAULT_DATASET_OUTPUT_NAME,
            label="dataset_output_name",
        ),
    }


def pdb_output_name(*, config: Any | None = None, metadata: dict[str, Any] | None = None) -> str:
    if config is not None:
        return output_files_from_config(config)["pdb"]
    return output_files_from_metadata(metadata)["pdb"]


def dataset_output_name(*, config: Any | None = None, metadata: dict[str, Any] | None = None) -> str:
    if config is not None:
        return output_files_from_config(config)["dataset"]
    return output_files_from_metadata(metadata)["dataset"]


def pdb_output_path(out_dir: Path, *, config: Any | None = None, metadata: dict[str, Any] | None = None) -> Path:
    return Path(out_dir) / pdb_output_name(config=config, metadata=metadata)


def dataset_output_path(out_dir: Path, *, config: Any | None = None, metadata: dict[str, Any] | None = None) -> Path:
    return Path(out_dir) / dataset_output_name(config=config, metadata=metadata)
