from __future__ import annotations

import numpy as np
import biotite.structure as struc
from biotite.structure import info as struc_info

from .base import BaseManipulation


def _vdw_radius(element: str) -> float:
    radius = struc_info.vdw_radius_single(str(element).strip().title())
    if radius is None:
        return 1.7
    return float(radius)


class StructureClashesManipulation(BaseManipulation):
    name = "structure_clashes"
    prefix = "clash"
    analysis_category = "quality_control"
    prepare_section = "quality_control"
    clash_overlap_tolerance = 0.4
    search_radius = 3.5

    def run(self, ctx):
        arr = ctx.aa
        if arr is None or len(arr) == 0:
            return

        valid_mask = ~np.isnan(arr.coord).any(axis=1)
        atoms = arr[valid_mask]
        if len(atoms) == 0:
            yield {
                "__table__": "structures",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "has_clash": False,
                "n_clashing_atom_pairs": 0,
                "n_clashing_atoms": 0,
            }
            return

        cell_list = struc.CellList(atoms.coord, cell_size=self.search_radius)
        near = cell_list.get_atoms(atoms.coord, self.search_radius, as_mask=True)
        if near.size == 0:
            clash_pairs: list[tuple[int, int]] = []
        else:
            near = np.triu(np.asarray(near, dtype=bool), k=1)
            candidate_i, candidate_j = np.nonzero(near)
            clash_pairs = []
            for i, j in zip(candidate_i.tolist(), candidate_j.tolist()):
                same_chain = str(atoms.chain_id[i]) == str(atoms.chain_id[j])
                same_residue = same_chain and int(atoms.res_id[i]) == int(atoms.res_id[j])
                adjacent_residue = same_chain and abs(int(atoms.res_id[i]) - int(atoms.res_id[j])) <= 1
                if same_residue or adjacent_residue:
                    continue

                radius_sum = _vdw_radius(str(atoms.element[i])) + _vdw_radius(str(atoms.element[j]))
                cutoff = radius_sum - float(self.clash_overlap_tolerance)
                if cutoff <= 0:
                    continue
                distance = float(np.linalg.norm(atoms.coord[i] - atoms.coord[j]))
                if distance < cutoff:
                    clash_pairs.append((i, j))

        clashing_atoms = {idx for pair in clash_pairs for idx in pair}
        yield {
            "__table__": "structures",
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "has_clash": bool(clash_pairs),
            "n_clashing_atom_pairs": int(len(clash_pairs)),
            "n_clashing_atoms": int(len(clashing_atoms)),
        }
