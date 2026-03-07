from __future__ import annotations

from typing import Any

from ..base import Context
from .calculation.interface_analysis.interface_metrics import interface_contact_summary


def interface_contact_summary_for_roles(
    ctx: Context,
    *,
    left_role: str,
    right_role: str,
    contact_distance: float,
    cell_size: float | None = None,
) -> dict[str, Any] | None:
    left = ctx.roles.get(left_role)
    right = ctx.roles.get(right_role)
    if left is None or right is None or len(left) == 0 or len(right) == 0:
        return None
    return ctx.get_annotation(
        "pdb",
        "interface",
        left_role,
        right_role,
        "contact_summary",
        f"cutoff={float(contact_distance):.6f}",
        "cell=none" if cell_size is None else f"cell={float(cell_size):.6f}",
        factory=lambda: interface_contact_summary(
            left,
            right,
            contact_distance=contact_distance,
            cell_size=cell_size,
        ),
    )
