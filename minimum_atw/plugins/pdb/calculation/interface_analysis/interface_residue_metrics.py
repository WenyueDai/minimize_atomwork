from __future__ import annotations

from ...annotations import interface_contact_summary_for_roles
from ....base import Context, InterfacePlugin
from .interface_metrics import (
    _cell_size,
    format_residue_labels,
    residue_contact_pair_tokens,
    residue_infos,
    summarize_residue_properties,
)


class InterfaceMetricsPlugin(InterfacePlugin):
    name = "interface_metrics"
    prefix = "ifm"

    def run(self, ctx: Context):
        cutoff = float(ctx.config.contact_distance)
        cell_size = _cell_size(getattr(ctx.config, "interface_cell_size", None), cutoff)

        for left_role, right_role, _left, _right in self.iter_role_pairs(ctx):
            summary = interface_contact_summary_for_roles(
                ctx,
                left_role=left_role,
                right_role=right_role,
                contact_distance=cutoff,
                cell_size=cell_size,
            )
            if summary is None:
                continue

            pair_list = summary["residue_contact_pairs"]
            left_contact_atoms = summary["left_contact_atoms"]
            right_contact_atoms = summary["right_contact_atoms"]
            if not pair_list:
                continue

            yield {
                **self.pair_identity_row(ctx, left_role=left_role, right_role=right_role),
                "contact_distance": cutoff,
                "cell_size": cell_size,
                "n_residue_contact_pairs": int(len(pair_list)),
                "residue_contact_pairs": residue_contact_pair_tokens(pair_list),
                "left_interface_residue_labels": format_residue_labels(left_contact_atoms),
                "right_interface_residue_labels": format_residue_labels(right_contact_atoms),
                **summarize_residue_properties(residue_infos(left_contact_atoms), "left"),
                **summarize_residue_properties(residue_infos(right_contact_atoms), "right"),
            }
