from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from biotite.structure.io import save_structure

from ..base import Context, InterfacePlugin


def _parse_scorefile(score_path: Path) -> dict[str, float | int]:
    if not score_path.exists():
        return {}
    lines = [line.strip() for line in score_path.read_text().splitlines() if line.strip()]
    header = next((line for line in lines if line.startswith("SCORE:") and "description" in line), None)
    values = next((line for line in reversed(lines) if line.startswith("SCORE:") and "description" not in line), None)
    if header is None or values is None:
        return {}

    keys = header.split()[1:]
    vals = values.split()[1:]
    wanted = {
        "interface_dG": "interface_dg",
        "dG_separated": "interface_dg_separated",
        "dSASA_int": "interface_dsasa",
        "packstat": "interface_packstat",
    }
    out: dict[str, float | int] = {}
    for key, value in zip(keys, vals):
        if key not in wanted:
            continue
        try:
            out[wanted[key]] = float(value)
        except ValueError:
            continue
    return out


class RosettaInterfaceExamplePlugin(InterfacePlugin):
    name = "rosetta_interface_example"
    prefix = "rosetta"
    execution = "external"

    def available(self, ctx: Context) -> tuple[bool, str]:
        executable = ctx.config.rosetta_executable or shutil.which("InterfaceAnalyzer.static.linuxgccrelease")
        if executable:
            return True, ""
        return False, "Rosetta InterfaceAnalyzer executable not found"

    def run(self, ctx: Context):
        executable = ctx.config.rosetta_executable or shutil.which("InterfaceAnalyzer.static.linuxgccrelease")
        if not executable:
            return
        database = ctx.config.rosetta_database

        for left_role, right_role, left, right in self.iter_role_pairs(ctx):
            left_chain_ids = sorted({str(chain_id) for chain_id in left.chain_id.astype(str)})
            right_chain_ids = sorted({str(chain_id) for chain_id in right.chain_id.astype(str)})
            if not left_chain_ids or not right_chain_ids:
                continue
            if set(left_chain_ids) & set(right_chain_ids):
                continue

            pair_atoms = ctx.aa[np.isin(ctx.aa.chain_id.astype(str), left_chain_ids + right_chain_ids)]
            interface_spec = f"{''.join(left_chain_ids)}_{''.join(right_chain_ids)}"
            with tempfile.TemporaryDirectory(prefix="minimum_atw_rosetta_") as tmp_dir:
                tmp = Path(tmp_dir)
                pair_path = tmp / "pair.pdb"
                score_path = tmp / "interface.sc"
                save_structure(pair_path, pair_atoms)

                command = [executable]
                if database:
                    command.extend(["-database", database])
                command.extend(
                    [
                        "-in:file:s",
                        str(pair_path),
                        "-interface",
                        interface_spec,
                        "-out:file:score_only",
                        str(score_path),
                        "-mute",
                        "all",
                    ]
                )
                try:
                    subprocess.run(command, capture_output=True, text=True, check=True)
                except subprocess.CalledProcessError:
                    continue
                metrics = _parse_scorefile(score_path)
                if not metrics:
                    continue
                yield {
                    **self.pair_identity_row(ctx, left_role=left_role, right_role=right_role),
                    "database_path": database,
                    "interface_spec": interface_spec,
                    **metrics,
                }
