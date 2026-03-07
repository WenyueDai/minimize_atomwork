from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins.dataset.calculation import DATASET_CALCULATION_REGISTRY
from ..plugins.dataset.manipulation import DATASET_MANIPULATION_REGISTRY
from ..plugins.dataset.quality_control import DATASET_QUALITY_CONTROL_REGISTRY
from ..plugins.pdb.calculation import PDB_CALCULATION_REGISTRY
from ..plugins.pdb.manipulation import PDB_MANIPULATION_REGISTRY
from ..plugins.pdb.quality_control import PDB_QUALITY_CONTROL_REGISTRY


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
    analysis_category: str
    stage: str
    config_key: str
    execution: str


EXTENSION_CLASSES: dict[str, ExtensionClassSpec] = {
    "pdb_quality_control": ExtensionClassSpec(
        name="pdb_quality_control",
        display_name="PDB Quality Controls",
        config_key="quality_controls",
        stage="prepare",
        description="Per-structure checks that annotate PDB-derived records without changing coordinates.",
    ),
    "pdb_manipulation": ExtensionClassSpec(
        name="pdb_manipulation",
        display_name="PDB Manipulations",
        config_key="structure_manipulations",
        stage="prepare",
        description="Prepare-stage transforms applied independently to each structure.",
    ),
    "dataset_quality_control": ExtensionClassSpec(
        name="dataset_quality_control",
        display_name="Dataset Quality Controls",
        config_key="dataset_quality_controls",
        stage="prepare",
        description="Dataset-scope validation that depends on shared dataset context.",
    ),
    "dataset_manipulation": ExtensionClassSpec(
        name="dataset_manipulation",
        display_name="Dataset Manipulations",
        config_key="dataset_manipulations",
        stage="prepare",
        description="Prepare-stage transforms that depend on shared dataset context or cross-structure state.",
    ),
    "pdb_calculation": ExtensionClassSpec(
        name="pdb_calculation",
        display_name="PDB Calculations",
        config_key="plugins",
        stage="run-plugin",
        description="Per-structure/per-chain/per-role/per-interface calculations merged into normalized output tables.",
    ),
    "dataset_calculation": ExtensionClassSpec(
        name="dataset_calculation",
        display_name="Dataset Calculations",
        config_key="dataset_analyses",
        stage="analyze-dataset",
        description="Post-merge analyses that aggregate across the full dataset outputs.",
    ),
}


def _config_key_for_unit(unit: Any, spec: ExtensionClassSpec | None) -> str:
    if spec is None:
        return ""
    return spec.config_key


def _info_from_unit(name: str, unit: Any) -> ExtensionInfo:
    extension_class = str(getattr(unit, "extension_class", "unknown"))
    spec = EXTENSION_CLASSES.get(extension_class)
    return ExtensionInfo(
        name=name,
        extension_class=extension_class,
        analysis_category=str(getattr(unit, "analysis_category", "generic")),
        stage=spec.stage if spec else "unknown",
        config_key=_config_key_for_unit(unit, spec),
        execution=str(getattr(unit, "execution", "n/a")),
    )


def extension_catalog() -> dict[str, list[ExtensionInfo]]:
    grouped: dict[str, list[ExtensionInfo]] = {key: [] for key in EXTENSION_CLASSES}

    for name, unit in sorted(PDB_QUALITY_CONTROL_REGISTRY.items()):
        grouped["pdb_quality_control"].append(_info_from_unit(name, unit))
    for name, unit in sorted(PDB_MANIPULATION_REGISTRY.items()):
        grouped["pdb_manipulation"].append(_info_from_unit(name, unit))
    for name, unit in sorted(DATASET_QUALITY_CONTROL_REGISTRY.items()):
        grouped["dataset_quality_control"].append(_info_from_unit(name, unit))
    for name, unit in sorted(DATASET_MANIPULATION_REGISTRY.items()):
        grouped["dataset_manipulation"].append(_info_from_unit(name, unit))
    for name, unit in sorted(PDB_CALCULATION_REGISTRY.items()):
        grouped["pdb_calculation"].append(_info_from_unit(name, unit))
    for name, unit in sorted(DATASET_CALCULATION_REGISTRY.items()):
        grouped["dataset_calculation"].append(_info_from_unit(name, unit))
    return grouped


def extension_catalog_by_category() -> dict[str, list[ExtensionInfo]]:
    grouped: dict[str, list[ExtensionInfo]] = {}
    for items in extension_catalog().values():
        for item in items:
            grouped.setdefault(item.analysis_category, []).append(item)
    for category in grouped:
        grouped[category] = sorted(grouped[category], key=lambda item: (item.extension_class, item.name))
    return dict(sorted(grouped.items()))
