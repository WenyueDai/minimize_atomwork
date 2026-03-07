from __future__ import annotations

import numpy as np
import biotite.structure as struc

from .base import BaseQualityControl


def _interface_chain_pairs(ctx) -> set[tuple[str, str]]:
    chain_pairs: set[tuple[str, str]] = set()
    role_map = getattr(ctx, "role_map", {}) or {}
    for left_role, right_role in getattr(ctx.config, "interface_pairs", []) or []:
        for left_chain in role_map.get(left_role, ()):
            for right_chain in role_map.get(right_role, ()):
                left_chain_id = str(left_chain)
                right_chain_id = str(right_chain)
                if not left_chain_id or not right_chain_id or left_chain_id == right_chain_id:
                    continue
                chain_pairs.add((left_chain_id, right_chain_id))
                chain_pairs.add((right_chain_id, left_chain_id))
    return chain_pairs


class StructureClashesManipulation(BaseQualityControl):
    name = "structure_clashes"
    prefix = "clash"

    def run(self, ctx):
        arr = ctx.aa
        if arr is None or len(arr) == 0:
            return

        valid_mask = ~np.isnan(arr.coord).any(axis=1)
        atoms = arr[valid_mask]
        if len(atoms) == 0:
            yield {
                "grain": "structure",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "has_clash": False,
                "n_clashing_atom_pairs": 0,
                "n_clashing_atoms": 0,
            }
            return

        clash_distance = float(getattr(ctx.config, "clash_distance", 2.0) or 2.0)
        clash_scope = str(getattr(ctx.config, "clash_scope", "all") or "all").strip().lower()
        interface_chain_pairs = _interface_chain_pairs(ctx) if clash_scope == "interface_only" else set()

        cell_list = struc.CellList(atoms.coord, cell_size=clash_distance)
        near = cell_list.get_atoms(atoms.coord, clash_distance, as_mask=True)
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
                if clash_scope == "inter_chain" and same_chain:
                    continue
                if clash_scope == "interface_only":
                    chain_pair = (str(atoms.chain_id[i]), str(atoms.chain_id[j]))
                    if chain_pair not in interface_chain_pairs:
                        continue

                distance = float(np.linalg.norm(atoms.coord[i] - atoms.coord[j]))
                if distance < clash_distance:
                    clash_pairs.append((i, j))

        clashing_atoms = {idx for pair in clash_pairs for idx in pair}
        yield {
            "grain": "structure",
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "has_clash": bool(clash_pairs),
            "n_clashing_atom_pairs": int(len(clash_pairs)),
            "n_clashing_atoms": int(len(clashing_atoms)),
        }
