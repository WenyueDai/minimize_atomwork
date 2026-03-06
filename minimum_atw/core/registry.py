from __future__ import annotations

import importlib.metadata
from typing import Any


def load_registry(
    *,
    builtin_items: dict[str, Any],
    entry_point_group: str,
    label: str,
    require_prefix: bool = False,
) -> dict[str, Any]:
    registry = dict(builtin_items)
    try:
        for entry_point in importlib.metadata.entry_points(group=entry_point_group):
            try:
                item_class = entry_point.load()
                registry[entry_point.name] = item_class()
            except Exception as exc:
                print(f"Warning: Failed to load {label} {entry_point.name}: {exc}")
    except Exception as exc:
        print(f"Warning: Failed to load {label} entry points: {exc}")

    seen_names: set[str] = set()
    seen_prefixes: dict[str, str] = {}
    for registry_name, unit in sorted(registry.items()):
        unit_name = str(getattr(unit, "name", "") or registry_name)
        if not unit_name:
            raise ValueError(f"{label} '{registry_name}' must define a non-empty name")
        if unit_name in seen_names:
            raise ValueError(f"Duplicate {label} name '{unit_name}'")
        seen_names.add(unit_name)

        prefix = str(getattr(unit, "prefix", "") or "")
        if require_prefix and not prefix:
            raise ValueError(f"{label} '{unit_name}' must define a non-empty prefix")
        if prefix:
            other = seen_prefixes.get(prefix)
            if other is not None and other != unit_name:
                raise ValueError(f"Duplicate {label} prefix '{prefix}' used by '{other}' and '{unit_name}'")
            seen_prefixes[prefix] = unit_name

    return registry


def instantiate_unit(unit: Any) -> Any:
    try:
        return type(unit)()
    except Exception as exc:
        raise TypeError(f"Could not instantiate fresh unit from {type(unit).__name__}") from exc
