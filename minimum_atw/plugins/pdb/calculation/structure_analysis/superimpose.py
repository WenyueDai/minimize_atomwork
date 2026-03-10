from __future__ import annotations

from pathlib import Path

import biotite.structure as struc
from biotite.structure.io import save_structure

from ....base import BasePlugin, Context
from ...superimpose_common import (
    iter_chain_rmsd,
    load_reference_structure,
    matched_atom_indices,
    superimpose_complex,
)
from .....runtime.workspace import prepared_filename, superimposed_structures_dir


def _resolve_reference(ctx: Context, params: dict) -> tuple[str | None, bool]:
    """Return (reference_path, already_superimposed).

    already_superimposed is True when the reference is inherited from the
    prepare-phase ``superimpose_to_reference`` step, meaning the prepared
    coordinates are already aligned and re-superimposition can be skipped.

    Priority:
      1. Explicit ``reference_path`` on this plugin — always re-superimposes.
      2. Reference inherited from ``plugin_params.superimpose_to_reference``
         or top-level ``superimpose_reference_path`` — skips re-superimpose
         when ``superimpose_to_reference`` is present in manipulations.
    """
    explicit = params.get("reference_path")
    if explicit:
        return str(Path(explicit).expanduser().resolve()), False

    prepare_ran = any(
        m.get("name") == "superimpose_to_reference"
        for m in getattr(ctx.config, "manipulations", [])
    )
    prepare_params = dict(
        getattr(ctx.config, "plugin_params", {}).get("superimpose_to_reference", {})
    )
    inherited_ref = prepare_params.get("reference_path") or getattr(
        ctx.config, "superimpose_reference_path", None
    )
    if inherited_ref:
        return str(Path(inherited_ref).expanduser().resolve()), prepare_ran

    return None, False


class SuperimposePlugin(BasePlugin):
    name = "structure_rmsd"
    prefix = "rmsd"
    grain = "structure"

    def __init__(self) -> None:
        self._reference: struc.AtomArray | None = None
        self._reference_path: str | None = None
        self._already_superimposed: bool = False

    def _persist_transformed_structure(self, ctx: Context, transformed: struc.AtomArray) -> str:
        out_dir = Path(ctx.config.out_dir).resolve()
        target_dir = superimposed_structures_dir(out_dir) / self.name
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / prepared_filename(Path(ctx.path))
        save_structure(target_path, transformed)
        return str(target_path.resolve())

    def run(self, ctx: Context):
        params = self.plugin_params(ctx)
        persist_transformed = bool(params.get("persist_transformed_structures", False))

        if self._reference is None:
            ref_path, already_superimposed = _resolve_reference(ctx, params)
            if ref_path:
                self._reference_path = ref_path
                self._reference = load_reference_structure(ref_path)
                self._already_superimposed = already_superimposed
            else:
                self._reference = ctx.aa.copy()
                self._reference_path = ctx.path
                self._already_superimposed = False
                row = {
                    "grain": "structure",
                    "path": ctx.path,
                    "assembly_id": ctx.assembly_id,
                    "note": "reference_structure",
                }
                if persist_transformed:
                    row["transformed_path"] = self._persist_transformed_structure(ctx, ctx.aa.copy())
                yield row
                return

        fixed = self._reference
        on_chains_cfg = params.get("on_chains") or getattr(ctx.config, "superimpose_on_chains", [])
        on_chains = tuple(str(c) for c in on_chains_cfg if str(c))

        if self._already_superimposed:
            fixed_idx, mobile_idx = matched_atom_indices(fixed, ctx.aa)
            if len(fixed_idx) == 0:
                return
            shared_atoms_rmsd = float(struc.rmsd(fixed[fixed_idx], ctx.aa[mobile_idx]))
            row = {
                "grain": "structure",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "reference_path": self._reference_path,
                "on_chains": ";".join(on_chains),
                "anchor_atoms": 0,
                "alignment_method": "pre_aligned",
                "shared_atoms_rmsd": shared_atoms_rmsd,
                "shared_atoms_count": int(len(fixed_idx)),
            }
            if persist_transformed:
                row["transformed_path"] = self._persist_transformed_structure(ctx, ctx.aa.copy())
            yield row
            yield from iter_chain_rmsd(
                fixed, ctx.aa, fixed_idx, mobile_idx,
                path=ctx.path, assembly_id=ctx.assembly_id,
            )
            return

        result = superimpose_complex(reference=fixed, mobile=ctx.aa.copy(), on_chains=on_chains)
        shared_atoms_rmsd = float(
            struc.rmsd(fixed[result.fixed_idx], result.fitted_complex[result.mobile_idx])
        )
        row = {
            "grain": "structure",
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "reference_path": self._reference_path,
            "on_chains": ";".join(on_chains),
            "anchor_atoms": int(len(result.fixed_anchor_idx)),
            "alignment_method": result.alignment_method,
            "shared_atoms_rmsd": shared_atoms_rmsd,
            "shared_atoms_count": int(len(result.fixed_idx)),
        }
        if persist_transformed:
            row["transformed_path"] = self._persist_transformed_structure(ctx, result.fitted_complex)
        yield row
        yield from iter_chain_rmsd(
            fixed, result.fitted_complex,
            result.fixed_idx, result.mobile_idx,
            path=ctx.path, assembly_id=ctx.assembly_id,
        )
