from __future__ import annotations

from pathlib import Path

import biotite.structure as struc

from ..superimpose_common import iter_chain_rmsd, load_reference_structure, superimpose_complex
from .base import BaseStructureManipulation


class SuperimposeToReferenceManipulation(BaseStructureManipulation):
    name = "superimpose_to_reference"
    prefix = "sup"

    def __init__(self) -> None:
        self._reference: struc.AtomArray | None = None
        self._reference_path: str | None = None

    def run(self, ctx):
        params = self.plugin_params(ctx)
        ref_path = params.get("reference_path") or getattr(ctx.config, "superimpose_reference_path", None)
        on_chains_cfg = params.get("on_chains") or getattr(ctx.config, "superimpose_on_chains", [])
        on_chains = tuple(str(chain_id) for chain_id in on_chains_cfg if str(chain_id))

        if self._reference is None:
            if ref_path:
                self._reference_path = str(Path(ref_path).expanduser().resolve())
                self._reference = load_reference_structure(self._reference_path)
            else:
                self._reference = ctx.aa.copy()
                self._reference_path = ctx.path
                yield {
                    "grain": "structure",
                    "path": ctx.path,
                    "assembly_id": ctx.assembly_id,
                    "note": "reference_structure",
                }
                return

        result = superimpose_complex(
            reference=self._reference,
            mobile=ctx.aa.copy(),
            on_chains=on_chains,
        )
        ctx.aa = result.fitted_complex
        ctx.rebuild_views()

        shared_atoms_rmsd = float(struc.rmsd(self._reference[result.fixed_idx], result.fitted_complex[result.mobile_idx]))
        yield {
            "grain": "structure",
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "reference_path": self._reference_path,
            "on_chains": ";".join(on_chains),
            "anchor_atoms": int(len(result.fixed_anchor_idx)),
            "alignment_method": result.alignment_method,
            "shared_atoms_rmsd": shared_atoms_rmsd,
            "shared_atoms_count": int(len(result.fixed_idx)),
            "coordinates_applied": True,
        }
        yield from iter_chain_rmsd(
            self._reference, result.fitted_complex,
            result.fixed_idx, result.mobile_idx,
            path=ctx.path, assembly_id=ctx.assembly_id,
        )
