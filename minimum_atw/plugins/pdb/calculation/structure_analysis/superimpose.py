from __future__ import annotations

from pathlib import Path

import biotite.structure as struc
from biotite.structure.io import save_structure

from ....base import BasePlugin, Context
from ...superimpose_common import load_reference_structure, superimpose_complex
from .....runtime.workspace import prepared_filename, superimposed_structures_dir


class SuperimposePlugin(BasePlugin):
    name = "structure_rmsd"
    prefix = "rmsd"
    grain = "structure"
    analysis_category = "structure_analysis"

    def __init__(self) -> None:
        self._reference: struc.AtomArray | None = None
        self._reference_path: str | None = None

    def available(self, ctx: Context) -> tuple[bool, str]:
        return True, ""

    def _persist_transformed_structure(self, ctx: Context, transformed: struc.AtomArray) -> str:
        out_dir = Path(ctx.config.out_dir).resolve()
        target_dir = superimposed_structures_dir(out_dir) / self.name
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / prepared_filename(Path(ctx.path))
        save_structure(target_path, transformed)
        return str(target_path.resolve())

    def run(self, ctx: Context):
        params = self.plugin_params(ctx)
        ref_path = params.get("reference_path") or getattr(ctx.config, "superimpose_reference_path", None)
        on_chains_cfg = params.get("on_chains") or getattr(ctx.config, "superimpose_on_chains", [])
        persist_transformed = bool(params.get("persist_transformed_structures", False))
        if self._reference is None:
            if ref_path:
                self._reference_path = str(Path(ref_path).expanduser().resolve())
                self._reference = load_reference_structure(self._reference_path)
            else:
                self._reference = ctx.aa.copy()
                self._reference_path = ctx.path
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
        on_chains = tuple(str(chain_id) for chain_id in on_chains_cfg if str(chain_id))
        result = superimpose_complex(
            reference=fixed,
            mobile=ctx.aa.copy(),
            on_chains=on_chains,
        )
        shared_atoms_rmsd = float(struc.rmsd(fixed[result.fixed_idx], result.fitted_complex[result.mobile_idx]))
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

        fixed_chain = fixed.chain_id[result.fixed_idx].astype(str)
        mobile_chain = result.fitted_complex.chain_id[result.mobile_idx].astype(str)
        common_chain_ids = sorted(set(fixed_chain) & set(mobile_chain))
        for chain_id in common_chain_ids:
            chain_mask = (fixed_chain == chain_id) & (mobile_chain == chain_id)
            chain_fixed_idx = result.fixed_idx[chain_mask]
            chain_mobile_idx = result.mobile_idx[chain_mask]
            if len(chain_fixed_idx) == 0:
                continue
            chain_rmsd = float(struc.rmsd(fixed[chain_fixed_idx], result.fitted_complex[chain_mobile_idx]))
            yield {
                "grain": "chain",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "chain_id": str(chain_id),
                "rmsd": chain_rmsd,
                "matched_atoms": int(len(chain_fixed_idx)),
            }
