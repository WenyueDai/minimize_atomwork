from __future__ import annotations

from typing import Any, Literal

import biotite.structure as struc
import numpy as np
from biotite.sequence import ProteinSequence

from ..base import Context


ScopeKind = Literal["structure", "chain", "role"]


def residue_code(res_name: str) -> str:
    try:
        return ProteinSequence.convert_letter_3to1(str(res_name))
    except Exception:
        return "X"


def residue_starts(arr, *, add_exclusive_stop: bool = False) -> np.ndarray:
    if arr is None or len(arr) == 0:
        if add_exclusive_stop:
            return np.asarray([0], dtype=int)
        return np.asarray([], dtype=int)
    return np.asarray(struc.get_residue_starts(arr, add_exclusive_stop=add_exclusive_stop), dtype=int)


def iter_unique_residues(arr):
    if arr is None or len(arr) == 0:
        return
    starts = residue_starts(arr, add_exclusive_stop=True)
    for start, stop in zip(starts[:-1], starts[1:]):
        atom = arr[start]
        yield {
            "chain_id": str(atom.chain_id),
            "res_id": int(atom.res_id),
            "res_name": str(atom.res_name),
            "atoms": arr[start:stop],
        }


def residue_infos(arr) -> list[dict[str, Any]]:
    infos: list[dict[str, Any]] = []
    for info in iter_unique_residues(arr):
        entry = dict(info)
        entry["aa"] = residue_code(entry["res_name"])
        infos.append(entry)
    return infos


def chain_residue_entries(arr) -> list[tuple[str, int, str]]:
    return [(info["chain_id"], info["res_id"], info["aa"]) for info in residue_infos(arr)]


def residue_sequence(arr) -> str:
    return "".join(res_code for _chain_id, _res_id, res_code in chain_residue_entries(arr))


def sequences_by_chain(arr) -> dict[str, str]:
    if arr is None or len(arr) == 0:
        return {}
    out: dict[str, str] = {}
    for chain_id in sorted({str(chain_id) for chain_id in arr.chain_id.astype(str)}):
        chain_arr = arr[arr.chain_id.astype(str) == chain_id]
        out[chain_id] = residue_sequence(chain_arr)
    return out


def unique_residue_count(arr) -> int:
    return int(max(0, residue_starts(arr).size))


def _scope_atoms(ctx: Context, scope_kind: ScopeKind, scope_name: str | None):
    if scope_kind == "structure":
        return ctx.aa
    if scope_kind == "chain":
        return ctx.chains.get(str(scope_name))
    if scope_kind == "role":
        return ctx.roles.get(str(scope_name))
    raise ValueError(f"unsupported scope_kind={scope_kind!r}")


def _scope_cache_key(scope_kind: ScopeKind, scope_name: str | None, annotation_name: str) -> tuple[str, ...]:
    if scope_kind == "structure":
        return ("pdb", "structure", annotation_name)
    return ("pdb", scope_kind, str(scope_name), annotation_name)


def _scope_annotation(ctx: Context, scope_kind: ScopeKind, scope_name: str | None, annotation_name: str, factory):
    return ctx.get_annotation(*_scope_cache_key(scope_kind, scope_name, annotation_name), factory=factory)


def structure_sequences_by_chain(ctx: Context) -> dict[str, str]:
    return _scope_annotation(
        ctx,
        "structure",
        None,
        "sequences_by_chain",
        lambda: sequences_by_chain(ctx.aa),
    )


def chain_unique_residue_count(ctx: Context, chain_id: str) -> int:
    return _scope_annotation(
        ctx,
        "chain",
        chain_id,
        "unique_residue_count",
        lambda: unique_residue_count(_scope_atoms(ctx, "chain", chain_id)),
    )


def role_unique_residue_count(ctx: Context, role_name: str) -> int:
    return _scope_annotation(
        ctx,
        "role",
        role_name,
        "unique_residue_count",
        lambda: unique_residue_count(_scope_atoms(ctx, "role", role_name)),
    )


def role_sequences_by_chain(ctx: Context, role_name: str) -> dict[str, str]:
    return _scope_annotation(
        ctx,
        "role",
        role_name,
        "sequences_by_chain",
        lambda: sequences_by_chain(_scope_atoms(ctx, "role", role_name)),
    )


def role_residue_entries(ctx: Context, role_name: str) -> list[tuple[str, int, str]]:
    return _scope_annotation(
        ctx,
        "role",
        role_name,
        "residue_entries",
        lambda: chain_residue_entries(_scope_atoms(ctx, "role", role_name)),
    )


def interface_contact_summary_for_roles(
    ctx: Context,
    *,
    left_role: str,
    right_role: str,
    contact_distance: float,
    cell_size: float | None = None,
) -> "dict[str, Any] | None":
    from .calculation.interface_analysis.interface_metrics import interface_contact_summary

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
