from __future__ import annotations

"""
Minimal scaffold for adding a new plugin.

Copy the class you need into the appropriate plugin package:
- structure plugin -> minimum_atw/plugins/structure_analysis/
- chain plugin -> minimum_atw/plugins/structure_analysis/
- role plugin -> minimum_atw/plugins/structure_analysis/
- interface plugin -> minimum_atw/plugins/interface_analysis/

This file is intentionally not imported by the plugin registry.
"""

from .base import BasePlugin, ChainPlugin, Context, InterfacePlugin, RolePlugin


class TemplateStructurePlugin(BasePlugin):
    # Registry/config name. Must be unique.
    name = "template_structure"

    # Output column prefix. Must be unique across plugins.
    prefix = "tmpl"

    # Default target table if you omit "__table__" in emitted rows.
    table = "structures"

    # Execution metadata used by the grouped plugin runner.
    execution = "in_process"
    resource_class = "lightweight"   # or "heavy"
    execution_mode = "batched"       # or "isolated"
    failure_policy = "continue"      # or "raise"

    def available(self, ctx: Context) -> tuple[bool, str]:
        # Optional preflight check. Return (False, message) to skip cleanly.
        return True, ""

    def run(self, ctx: Context):
        # Emit one or more rows as plain dicts.
        # Identity columns must match the target table.
        # Non-identity fields are automatically prefixed as "<prefix>__<field>".
        yield {
            "__table__": "structures",
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "example_metric": float(len(ctx.aa)),
            "example_flag": bool(len(ctx.roles) > 0),
        }


class TemplateChainPlugin(ChainPlugin):
    name = "template_chain"
    prefix = "tmpl_chain"

    def run(self, ctx: Context):
        for chain_id, chain_aa in self.iter_chains(ctx):
            yield {
                **self.chain_identity_row(ctx, chain_id=chain_id),
                "n_atoms": int(len(chain_aa)),
            }


class TemplateRolePlugin(RolePlugin):
    name = "template_role"
    prefix = "tmpl_role"

    def run(self, ctx: Context):
        for role_name, role_aa in self.iter_roles(ctx):
            yield {
                **self.role_identity_row(ctx, role_name=role_name),
                "n_atoms": int(len(role_aa)),
            }


class TemplateInterfacePlugin(InterfacePlugin):
    name = "template_interface"
    prefix = "tmpl_iface"
    resource_class = "heavy"
    execution_mode = "isolated"

    def run(self, ctx: Context):
        for left_role, right_role, left, right in self.iter_role_pairs(ctx):
            yield {
                **self.pair_identity_row(ctx, left_role=left_role, right_role=right_role),
                "left_atoms": int(len(left)),
                "right_atoms": int(len(right)),
            }
