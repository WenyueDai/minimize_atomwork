from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins.dataset.calculation import DATASET_CALCULATION_REGISTRY
from ..plugins.pdb import PDB_PREPARE_REGISTRY
from ..plugins.pdb.calculation import PDB_CALCULATION_REGISTRY


@dataclass(frozen=True, slots=True)
class ExtensionClassSpec:
    name: str
    display_name: str
    config_key: str
    stage: str
    description: str


@dataclass(frozen=True, slots=True)
class ExtensionInfo:
    name: str
    extension_class: str
    stage: str
    config_key: str


EXTENSION_CLASSES: dict[str, ExtensionClassSpec] = {
    "pdb_prepare": ExtensionClassSpec(
        name="pdb_prepare",
        display_name="PDB Prepare Plugins",
        config_key="quality_controls / manipulations",
        stage="prepare",
        description="Per-structure checks and transforms run during prepare (QC before structure manipulations).",
    ),
    "pdb_calculation": ExtensionClassSpec(
        name="pdb_calculation",
        display_name="PDB Calculations",
        config_key="plugins",
        stage="run-plugin",
        description="Per-structure/chain/role/interface calculations merged into normalized output tables.",
    ),
    "dataset_calculation": ExtensionClassSpec(
        name="dataset_calculation",
        display_name="Dataset Calculations",
        config_key="dataset_analyses",
        stage="analyze-dataset",
        description="Post-merge analyses that aggregate across the full dataset outputs.",
    ),
}


def _info_from_unit(name: str, unit: Any, extension_class: str) -> ExtensionInfo:
    spec = EXTENSION_CLASSES[extension_class]
    return ExtensionInfo(
        name=name,
        extension_class=extension_class,
        stage=spec.stage,
        config_key=spec.config_key,
    )


def extension_catalog() -> dict[str, list[ExtensionInfo]]:
    grouped: dict[str, list[ExtensionInfo]] = {key: [] for key in EXTENSION_CLASSES}

    for name, unit in sorted(PDB_PREPARE_REGISTRY.items()):
        grouped["pdb_prepare"].append(_info_from_unit(name, unit, "pdb_prepare"))
    for name, unit in sorted(PDB_CALCULATION_REGISTRY.items()):
        grouped["pdb_calculation"].append(_info_from_unit(name, unit, "pdb_calculation"))
    for name, unit in sorted(DATASET_CALCULATION_REGISTRY.items()):
        grouped["dataset_calculation"].append(_info_from_unit(name, unit, "dataset_calculation"))
    return grouped
