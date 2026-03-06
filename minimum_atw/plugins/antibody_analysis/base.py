from __future__ import annotations

from importlib.util import find_spec

from ..base import BasePlugin, Context
from ..sequence import sequences_by_chain


DEFAULT_NUMBERING_ROLES = ("vh", "vl", "vhh")


def numbering_scheme_from_config(config) -> str:
    return str(getattr(config, "numbering_scheme", "imgt") or "imgt").strip().lower()


def cdr_definition_from_config(config) -> str | None:
    value = getattr(config, "cdr_definition", None)
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def antibody_role_names(ctx: Context) -> tuple[str, ...]:
    configured = tuple(str(role_name) for role_name in getattr(ctx.config, "numbering_roles", []) if str(role_name))
    if configured:
        return configured
    return tuple(role_name for role_name in DEFAULT_NUMBERING_ROLES if role_name in ctx.roles)


def antibody_role_sequences(ctx: Context) -> list[tuple[str, list[str], str]]:
    eligible: list[tuple[str, list[str], str]] = []
    for role_name in antibody_role_names(ctx):
        arr = ctx.roles.get(role_name)
        if arr is None or len(arr) == 0:
            continue
        seq_by_chain = sequences_by_chain(arr)
        non_empty = sorted((chain_id, seq) for chain_id, seq in seq_by_chain.items() if seq)
        if len(non_empty) != 1:
            continue
        chain_id, sequence = non_empty[0]
        eligible.append((role_name, [chain_id], sequence))
    return eligible


class AntibodyPluginBase(BasePlugin):
    """Base class for plugins using abnumber library."""

    table = "roles"
    analysis_category = "antibody_analysis"
    default_numbering_roles = DEFAULT_NUMBERING_ROLES

    def numbering_scheme(self, ctx: Context) -> str:
        return numbering_scheme_from_config(ctx.config)

    def cdr_definition(self, ctx: Context) -> str | None:
        return cdr_definition_from_config(ctx.config)

    def antibody_role_names(self, ctx: Context) -> tuple[str, ...]:
        return antibody_role_names(ctx)

    def _antibody_role_sequences(self, ctx: Context) -> list[tuple[str, list[str], str]]:
        return antibody_role_sequences(ctx)

    def eligible_antibody_role_names(self, ctx: Context) -> tuple[str, ...]:
        return tuple(role_name for role_name, _chain_ids, _sequence in self._antibody_role_sequences(ctx))

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
        yield from self._antibody_role_sequences(ctx)
