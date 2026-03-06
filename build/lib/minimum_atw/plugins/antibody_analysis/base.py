from __future__ import annotations

from importlib.util import find_spec

from ..base import BasePlugin, Context
from ..sequence import sequences_by_chain


class AntibodyPluginBase(BasePlugin):
    """Base class for plugins using abnumber library."""

    table = "roles"
    analysis_category = "antibody_analysis"
    default_numbering_roles = ("vh", "vl", "vhh")

    def antibody_role_names(self, ctx: Context) -> tuple[str, ...]:
        configured = tuple(str(role_name) for role_name in getattr(ctx.config, "numbering_roles", []) if str(role_name))
        if configured:
            return configured
        return tuple(role_name for role_name in self.default_numbering_roles if role_name in ctx.roles)

    def eligible_antibody_role_names(self, ctx: Context) -> tuple[str, ...]:
        eligible: list[str] = []
        for role_name in self.antibody_role_names(ctx):
            arr = ctx.roles.get(role_name)
            if arr is None or len(arr) == 0:
                continue
            seq_by_chain = sequences_by_chain(arr)
            non_empty = [chain_id for chain_id, seq in seq_by_chain.items() if seq]
            if len(non_empty) == 1:
                eligible.append(role_name)
        return tuple(eligible)

    def available(self, ctx: Context) -> tuple[bool, str]:
        if find_spec("abnumber") is None:
            return False, "abnumber is not installed"
        configured = self.antibody_role_names(ctx)
        if not configured:
            return False, "no antibody numbering roles found; set numbering_roles or use roles such as vh, vl, or vhh"
        if not self.eligible_antibody_role_names(ctx):
            return False, "antibody numbering roles must resolve to exactly one non-empty chain each"
        return True, ""

    def iter_antibody_roles(self, ctx: Context):
        for role_name in self.eligible_antibody_role_names(ctx):
            arr = ctx.roles.get(role_name)
            if arr is None or len(arr) == 0:
                continue
            seq_by_chain = sequences_by_chain(arr)
            non_empty = {chain_id: seq for chain_id, seq in seq_by_chain.items() if seq}
            if len(non_empty) != 1:
                continue
            chain_id, sequence = next(iter(sorted(non_empty.items())))
            yield role_name, [chain_id], sequence
