from __future__ import annotations

from typing import NamedTuple

from ..plugins.dataset.calculation import DATASET_CALCULATION_REGISTRY
from ..plugins.pdb import PDB_PREPARE_REGISTRY
from ..plugins.pdb.calculation import PDB_CALCULATION_REGISTRY


class ExtensionClassInfo(NamedTuple):
    display_name: str
    config_key: str
    stage: str


class ExtensionInfo(NamedTuple):
    name: str
    extension_class: str
    stage: str
    config_key: str


EXTENSION_CLASSES: dict[str, ExtensionClassInfo] = {
    "pdb_prepare": ExtensionClassInfo(
        display_name="PDB Prepare Plugins",
        config_key="quality_controls / manipulations",
        stage="prepare",
    ),
    "pdb_calculation": ExtensionClassInfo(
        display_name="PDB Calculations",
        config_key="plugins",
        stage="run-plugin",
    ),
    "dataset_calculation": ExtensionClassInfo(
        display_name="Dataset Calculations",
        config_key="dataset_analyses",
        stage="analyze-dataset",
    ),
}


def extension_catalog() -> dict[str, list[ExtensionInfo]]:
    """Return all registered extensions grouped by extension class."""
    result: dict[str, list[ExtensionInfo]] = {k: [] for k in EXTENSION_CLASSES}
    for name, _ in sorted(PDB_PREPARE_REGISTRY.items()):
        spec = EXTENSION_CLASSES["pdb_prepare"]
        result["pdb_prepare"].append(ExtensionInfo(name, "pdb_prepare", spec.stage, spec.config_key))
    for name, _ in sorted(PDB_CALCULATION_REGISTRY.items()):
        spec = EXTENSION_CLASSES["pdb_calculation"]
        result["pdb_calculation"].append(ExtensionInfo(name, "pdb_calculation", spec.stage, spec.config_key))
    for name, _ in sorted(DATASET_CALCULATION_REGISTRY.items()):
        spec = EXTENSION_CLASSES["dataset_calculation"]
        result["dataset_calculation"].append(ExtensionInfo(name, "dataset_calculation", spec.stage, spec.config_key))
    return result
