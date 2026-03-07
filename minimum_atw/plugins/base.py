from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, TypeVar

import numpy as np
import biotite.structure as struc


GrainName = Literal["structure", "chain", "role", "interface"]
_T = TypeVar("_T")


@dataclass
class Context:
    path: str
    assembly_id: str
    aa: struc.AtomArray
    role_map: dict[str, tuple[str, ...]]
    config: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    chains: dict[str, struc.AtomArray] = field(default_factory=dict)
    roles: dict[str, struc.AtomArray] = field(default_factory=dict)
    annotation_cache: dict[tuple[str, ...], Any] = field(default_factory=dict)

    def rebuild_views(self) -> None:
        self.annotation_cache.clear()
        self.chains = {}
        for chain_id in sorted({str(chain_id) for chain_id in self.aa.chain_id}):
            self.chains[chain_id] = self.aa[self.aa.chain_id == chain_id]
        self.roles = {}
        for role_name, chain_ids in self.role_map.items():
            if not chain_ids:
                continue
            mask = np.isin(self.aa.chain_id.astype(str), list(chain_ids))
            self.roles[role_name] = self.aa[mask]

    def get_annotation(self, *key_parts: str, factory: Callable[[], _T]) -> _T:
        key = tuple(str(part) for part in key_parts)
        if key not in self.annotation_cache:
            self.annotation_cache[key] = factory()
        return self.annotation_cache[key]


class BasePlugin:
    name = ""
    prefix = ""
    grain: GrainName = "structure"
    requires: list[str] = []

    def run(self, ctx: Context) -> Iterable[dict]:
        raise NotImplementedError

    def available(self, _ctx: Context) -> tuple[bool, str]:
        return True, ""

    def plugin_params(self, ctx: Context) -> dict:
        """Return plugin-local parameters from ctx.config.plugin_params[self.name]."""
        return dict(getattr(ctx.config, "plugin_params", {}).get(self.name, {}))


class InterfacePlugin(BasePlugin):
    grain: GrainName = "interface"

    def iter_role_pairs(self, ctx: Context):
        for left_role, right_role in ctx.config.interface_pairs:
            left = ctx.roles.get(left_role)
            right = ctx.roles.get(right_role)
            if left is None or right is None or len(left) == 0 or len(right) == 0:
                continue
            yield left_role, right_role, left, right

    def pair_identity_row(self, ctx: Context, *, left_role: str, right_role: str) -> dict[str, str]:
        return {
            "path": str(Path(ctx.path).resolve()),
            "assembly_id": ctx.assembly_id,
            "pair": f"{left_role}__{right_role}",
            "role_left": left_role,
            "role_right": right_role,
        }


class ChainPlugin(BasePlugin):
    grain: GrainName = "chain"

    def iter_chains(self, ctx: Context):
        for chain_id, chain_aa in ctx.chains.items():
            if len(chain_aa) == 0:
                continue
            yield chain_id, chain_aa

    def chain_identity_row(self, ctx: Context, *, chain_id: str) -> dict[str, str]:
        return {
            "path": str(Path(ctx.path).resolve()),
            "assembly_id": ctx.assembly_id,
            "chain_id": chain_id,
        }


class RolePlugin(BasePlugin):
    grain: GrainName = "role"

    def iter_roles(self, ctx: Context):
        for role_name, role_aa in ctx.roles.items():
            if len(role_aa) == 0:
                continue
            yield role_name, role_aa

    def role_identity_row(self, ctx: Context, *, role_name: str) -> dict[str, str]:
        return {
            "path": str(Path(ctx.path).resolve()),
            "assembly_id": ctx.assembly_id,
            "role": role_name,
        }
