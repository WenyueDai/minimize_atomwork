from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins import PLUGIN_REGISTRY
from ..plugins.dataset_analysis import DATASET_ANALYSIS_REGISTRY
from ..plugins.manipulation import MANIPULATION_REGISTRY


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
    "manipulation": ExtensionClassSpec(
        name="manipulation",
        display_name="Manipulations",
        config_key="manipulations",
        stage="prepare",
        description="Pre-calculation structure transforms that modify the shared context.",
    ),
    "record_plugin": ExtensionClassSpec(
        name="record_plugin",
        display_name="Record Plugins",
        config_key="plugins",
        stage="run-plugin",
        description="Per-structure/per-chain/per-role/per-interface calculations merged into normalized output tables.",
    ),
    "dataset_analysis": ExtensionClassSpec(
        name="dataset_analysis",
        display_name="Dataset Analyses",
        config_key="dataset_analyses",
        stage="analyze-dataset",
        description="Post-merge analyses that aggregate across the full dataset outputs.",
    ),
}


def _info_from_unit(name: str, unit: Any) -> ExtensionInfo:
    extension_class = str(getattr(unit, "extension_class", "unknown"))
    spec = EXTENSION_CLASSES.get(extension_class)
    return ExtensionInfo(
        name=name,
        extension_class=extension_class,
        analysis_category=str(getattr(unit, "analysis_category", "generic")),
        stage=spec.stage if spec else "unknown",
        config_key=spec.config_key if spec else "",
        execution=str(getattr(unit, "execution", "n/a")),
    )


def extension_catalog() -> dict[str, list[ExtensionInfo]]:
    grouped: dict[str, list[ExtensionInfo]] = {key: [] for key in EXTENSION_CLASSES}

    for name, unit in sorted(MANIPULATION_REGISTRY.items()):
        grouped["manipulation"].append(_info_from_unit(name, unit))
    for name, unit in sorted(PLUGIN_REGISTRY.items()):
        grouped["record_plugin"].append(_info_from_unit(name, unit))
    for name, unit in sorted(DATASET_ANALYSIS_REGISTRY.items()):
        grouped["dataset_analysis"].append(_info_from_unit(name, unit))
    return grouped


def extension_catalog_by_category() -> dict[str, list[ExtensionInfo]]:
    grouped: dict[str, list[ExtensionInfo]] = {}
    for items in extension_catalog().values():
        for item in items:
            grouped.setdefault(item.analysis_category, []).append(item)
    for category in grouped:
        grouped[category] = sorted(grouped[category], key=lambda item: (item.extension_class, item.name))
    return dict(sorted(grouped.items()))
