from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from minimum_atw.plugins.dataset.calculation.runtime import analyze_dataset_outputs
from minimum_atw.tests.helpers import read_pdb_grain


def _write_pdb(path: Path, chain_a_coords: list[tuple[float, float, float]], chain_b_coords: list[tuple[float, float, float]]) -> None:
    lines: list[str] = []
    atom_id = 1
    for res_id, coord in enumerate(chain_a_coords, start=1):
        x, y, z = coord
        lines.append(
            f"ATOM  {atom_id:5d}  CA  GLY A{res_id:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C"
        )
        atom_id += 1
    for res_id, coord in enumerate(chain_b_coords, start=1):
        x, y, z = coord
        lines.append(
            f"ATOM  {atom_id:5d}  CA  GLY B{res_id:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C"
        )
        atom_id += 1
    lines.extend(["TER", "END"])
    path.write_text("\n".join(lines) + "\n")


class DatasetClusterTests(unittest.TestCase):
    def test_cluster_defaults_to_left_and_right_jobs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_dataset_cluster_") as tmp_dir:
            root = Path(tmp_dir)
            p1 = root / "c1.pdb"
            p2 = root / "c2.pdb"
            p3 = root / "c3.pdb"
            _write_pdb(p1, [(0, 0, 0), (2, 0, 0)], [(0, 0, 0), (2, 0, 0)])
            _write_pdb(p2, [(0.1, 0, 0), (2.1, 0, 0)], [(0, 0, 0), (0, 2, 0)])
            _write_pdb(p3, [(0, 0, 0), (0, 2, 0)], [(0.1, 0, 0), (2.1, 0, 0)])

            pd.DataFrame(
                [
                    {
                        "path": str(p1),
                        "assembly_id": "1",
                        "pair": "antibody__antigen",
                        "role_left": "antibody",
                        "role_right": "antigen",
                        "iface__left_interface_residues": "A:1:G;A:2:G",
                        "iface__right_interface_residues": "B:1:G;B:2:G",
                    },
                    {
                        "path": str(p2),
                        "assembly_id": "1",
                        "pair": "antibody__antigen",
                        "role_left": "antibody",
                        "role_right": "antigen",
                        "iface__left_interface_residues": "A:1:G;A:2:G",
                        "iface__right_interface_residues": "B:1:G;B:2:G",
                    },
                    {
                        "path": str(p3),
                        "assembly_id": "1",
                        "pair": "antibody__antigen",
                        "role_left": "antibody",
                        "role_right": "antigen",
                        "iface__left_interface_residues": "A:1:G;A:2:G",
                        "iface__right_interface_residues": "B:1:G;B:2:G",
                    },
                ]
            ).to_parquet(root / "interfaces.parquet", index=False)

            summary = analyze_dataset_outputs(
                root,
                dataset_analyses=("cluster",),
                dataset_analysis_params={"cluster": {"distance_threshold": 0.3}},
            )

            result = read_pdb_grain(root, "interface").sort_values("path").reset_index(drop=True)
            dataset_result = pd.read_parquet(root / "dataset.parquet")

            self.assertEqual(summary["n_cluster_rows"], 3)
            self.assertEqual(summary["n_cluster_dataset_rows"], 0)
            self.assertEqual(summary["n_cluster_pdb_rows"], 3)
            self.assertTrue(dataset_result.empty)

            left_cluster_by_path = dict(zip(result["path"], result["cluster__left_cluster_id"], strict=False))
            right_cluster_by_path = dict(zip(result["path"], result["cluster__right_cluster_id"], strict=False))

            self.assertEqual(result["cluster__left_mode"].dropna().unique().tolist(), ["interface_ca"])
            self.assertEqual(result["cluster__right_mode"].dropna().unique().tolist(), ["interface_ca"])
            self.assertEqual(result["cluster__left_interface_side"].dropna().unique().tolist(), ["left"])
            self.assertEqual(result["cluster__right_interface_side"].dropna().unique().tolist(), ["right"])
            self.assertEqual(left_cluster_by_path[str(p1)], left_cluster_by_path[str(p2)])
            self.assertNotEqual(left_cluster_by_path[str(p1)], left_cluster_by_path[str(p3)])
            self.assertEqual(right_cluster_by_path[str(p1)], right_cluster_by_path[str(p3)])
            self.assertNotEqual(right_cluster_by_path[str(p1)], right_cluster_by_path[str(p2)])

    def test_legacy_interface_epitope_alias_maps_to_interface_ca(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_dataset_cluster_") as tmp_dir:
            root = Path(tmp_dir)
            p1 = root / "a1.pdb"
            p2 = root / "a2.pdb"
            _write_pdb(p1, [(0, 0, 0), (2, 0, 0)], [(9, 0, 0)])
            _write_pdb(p2, [(0.1, 0, 0), (2.1, 0, 0)], [(9, 0, 0)])

            pd.DataFrame(
                [
                    {
                        "path": str(p1),
                        "assembly_id": "1",
                        "pair": "antibody__antigen",
                        "role_left": "antibody",
                        "role_right": "antigen",
                        "iface__left_interface_residues": "A:1:G;A:2:G",
                    },
                    {
                        "path": str(p2),
                        "assembly_id": "1",
                        "pair": "antibody__antigen",
                        "role_left": "antibody",
                        "role_right": "antigen",
                        "iface__left_interface_residues": "A:1:G;A:2:G",
                    },
                ]
            ).to_parquet(root / "interfaces.parquet", index=False)

            summary = analyze_dataset_outputs(
                root,
                dataset_analyses=("cluster",),
                dataset_analysis_params={
                    "cluster": {
                        "mode": "interface_epitope_ca",
                        "interface_side": "left",
                        "distance_threshold": 0.3,
                    }
                },
            )

            result = read_pdb_grain(root, "interface").sort_values("path").reset_index(drop=True)
            dataset_result = pd.read_parquet(root / "dataset.parquet")

            self.assertEqual(summary["n_cluster_rows"], 2)
            self.assertEqual(summary["n_cluster_pdb_rows"], 2)
            self.assertTrue(dataset_result.empty)
            self.assertEqual(result["cluster__default_mode"].dropna().unique().tolist(), ["interface_ca"])
            self.assertEqual(result["cluster__default_interface_side"].dropna().unique().tolist(), ["left"])

    def test_multiple_named_jobs_emit_separate_cluster_assignments(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_dataset_cluster_") as tmp_dir:
            root = Path(tmp_dir)
            p1 = root / "m1.pdb"
            p2 = root / "m2.pdb"
            p3 = root / "m3.pdb"
            _write_pdb(p1, [(0, 0, 0), (2, 0, 0)], [(0, 0, 0), (2, 0, 0)])
            _write_pdb(p2, [(0.1, 0, 0), (2.1, 0, 0)], [(0, 0, 0), (0, 2, 0)])
            _write_pdb(p3, [(0, 0, 0), (0, 2, 0)], [(0.1, 0, 0), (2.1, 0, 0)])

            pd.DataFrame(
                [
                    {
                        "path": str(p1),
                        "assembly_id": "1",
                        "pair": "antibody__antigen",
                        "role_left": "antibody",
                        "role_right": "antigen",
                        "iface__left_interface_residues": "A:1:G;A:2:G",
                        "iface__right_interface_residues": "B:1:G;B:2:G",
                    },
                    {
                        "path": str(p2),
                        "assembly_id": "1",
                        "pair": "antibody__antigen",
                        "role_left": "antibody",
                        "role_right": "antigen",
                        "iface__left_interface_residues": "A:1:G;A:2:G",
                        "iface__right_interface_residues": "B:1:G;B:2:G",
                    },
                    {
                        "path": str(p3),
                        "assembly_id": "1",
                        "pair": "antibody__antigen",
                        "role_left": "antibody",
                        "role_right": "antigen",
                        "iface__left_interface_residues": "A:1:G;A:2:G",
                        "iface__right_interface_residues": "B:1:G;B:2:G",
                    },
                ]
            ).to_parquet(root / "interfaces.parquet", index=False)

            summary = analyze_dataset_outputs(
                root,
                dataset_analyses=("cluster",),
                dataset_analysis_params={
                    "cluster": {
                        "jobs": [
                            {
                                "name": "paratope",
                                "pair": "antibody__antigen",
                                "interface_side": "left",
                                "distance_threshold": 0.3,
                            },
                            {
                                "name": "epitope",
                                "pair": "antibody__antigen",
                                "interface_side": "right",
                                "distance_threshold": 0.3,
                            },
                        ]
                    }
                },
            )

            result = read_pdb_grain(root, "interface").sort_values("path").reset_index(drop=True)
            dataset_result = pd.read_parquet(root / "dataset.parquet")
            self.assertEqual(summary["n_cluster_rows"], 3)
            self.assertEqual(summary["n_cluster_pdb_rows"], 3)
            self.assertTrue(dataset_result.empty)

            epi_cluster_by_path = dict(zip(result["path"], result["cluster__epitope_cluster_id"], strict=False))
            para_cluster_by_path = dict(zip(result["path"], result["cluster__paratope_cluster_id"], strict=False))

            self.assertEqual(epi_cluster_by_path[str(p1)], epi_cluster_by_path[str(p3)])
            self.assertNotEqual(epi_cluster_by_path[str(p1)], epi_cluster_by_path[str(p2)])
            self.assertEqual(para_cluster_by_path[str(p1)], para_cluster_by_path[str(p2)])
            self.assertNotEqual(para_cluster_by_path[str(p1)], para_cluster_by_path[str(p3)])


if __name__ == "__main__":
    unittest.main()
