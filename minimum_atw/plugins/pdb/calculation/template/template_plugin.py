"""
Minimal scaffold for adding a new PDB calculation plugin.

Copy the class you need into the appropriate sub-package:
  structure / chain / role plugins  →  plugins/pdb/calculation/structure_analysis/
  interface plugins                 →  plugins/pdb/calculation/interface_analysis/

Then register the instance in plugins/pdb/calculation/__init__.py under _builtin_pdb_calculations().

This file is NOT imported by the plugin registry — it is a reference template only.
"""

from __future__ import annotations

from minimum_atw.plugins.base import BasePlugin, ChainPlugin, Context, InterfacePlugin, RolePlugin


class TemplateStructurePlugin(BasePlugin):
    """Emits one row per structure (grain = 'structure')."""

    name = "template_structure"
    prefix = "tmpl"

    def run(self, ctx: Context):
        yield {
            "grain": "structure",
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "example_metric": float(len(ctx.aa)),
            "example_flag": bool(len(ctx.roles) > 0),
        }


class TemplateChainPlugin(ChainPlugin):
    """Emits one row per chain (grain = 'chain')."""

    name = "template_chain"
    prefix = "tmpl_chain"

    def run(self, ctx: Context):
        for chain_id, chain_aa in self.iter_chains(ctx):
            yield {
                **self.chain_identity_row(ctx, chain_id=chain_id),
                "n_atoms": int(len(chain_aa)),
            }


class TemplateRolePlugin(RolePlugin):
    """Emits one row per role (grain = 'role')."""

    name = "template_role"
    prefix = "tmpl_role"

    def run(self, ctx: Context):
        for role_name, role_aa in self.iter_roles(ctx):
            yield {
                **self.role_identity_row(ctx, role_name=role_name),
                "n_atoms": int(len(role_aa)),
            }


class TemplateInterfacePlugin(InterfacePlugin):
    """Emits one row per interface pair (grain = 'interface')."""

    name = "template_interface"
    prefix = "tmpl_iface"

    def run(self, ctx: Context):
        for left_role, right_role, left, right in self.iter_role_pairs(ctx):
            yield {
                **self.pair_identity_row(ctx, left_role=left_role, right_role=right_role),
                "left_atoms": int(len(left)),
                "right_atoms": int(len(right)),
            }
