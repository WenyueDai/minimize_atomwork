from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from minimum_atw.plugins.dataset.calculation.runtime import analyze_dataset_outputs
from minimum_atw.tests.helpers import read_pdb_grain


def _write_pdb(path: Path, chain_a_coords: list[tuple[float, float, float]], chain_b_coords: list[tuple[float, float, float]] | None = None) -> None:
    lines: list[str] = []
    atom_id = 1
    for res_id, coord in enumerate(chain_a_coords, start=1):
        x, y, z = coord
        lines.append(
            f"ATOM  {atom_id:5d}  CA  GLY A{res_id:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C"
        )
        atom_id += 1
    for res_id, coord in enumerate(chain_b_coords or [], start=1):
        x, y, z = coord
        lines.append(
            f"ATOM  {atom_id:5d}  CA  GLY B{res_id:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C"
        )
        atom_id += 1
    lines.extend(["TER", "END"])
    path.write_text("\n".join(lines) + "\n")


class DatasetClusterTests(unittest.TestCase):
    def test_cluster_skips_when_mode_is_not_explicit(self) -> None:
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
                    {"grain": "interface", "path": str(p1), "assembly_id": "1", "pair": "antibody__antigen", "role_left": "antibody", "role_right": "antigen", "iface__left_interface_residues": "A:1:G;A:2:G", "iface__right_interface_residues": "B:1:G;B:2:G"},
                    {"grain": "interface", "path": str(p2), "assembly_id": "1", "pair": "antibody__antigen", "role_left": "antibody", "role_right": "antigen", "iface__left_interface_residues": "A:1:G;A:2:G", "iface__right_interface_residues": "B:1:G;B:2:G"},
                    {"grain": "interface", "path": str(p3), "assembly_id": "1", "pair": "antibody__antigen", "role_left": "antibody", "role_right": "antigen", "iface__left_interface_residues": "A:1:G;A:2:G", "iface__right_interface_residues": "B:1:G;B:2:G"},
                ]
            ).to_parquet(root / "pdb.parquet", index=False)

            summary = analyze_dataset_outputs(
                root,
                dataset_analyses=("cluster",),
                dataset_analysis_params={"cluster": {"distance_threshold": 0.3}},
            )

            result = read_pdb_grain(root, "interface").sort_values("path").reset_index(drop=True)
            dataset_result = pd.read_parquet(root / "dataset.parquet")

            self.assertEqual(summary["n_cluster_rows"], 0)
            self.assertEqual(summary["n_cluster_dataset_rows"], 0)
            self.assertEqual(summary["n_cluster_pdb_rows"], 0)
            self.assertTrue(dataset_result.empty)
            self.assertFalse(any(column.startswith("cluster__") for column in result.columns))

    def test_cluster_runs_left_and_right_jobs_when_mode_is_explicit(self) -> None:
        """Explicit mode still produces left and right cluster jobs by default."""
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
                    {"grain": "interface", "path": str(p1), "assembly_id": "1", "pair": "antibody__antigen", "role_left": "antibody", "role_right": "antigen", "iface__left_interface_residues": "A:1:G;A:2:G", "iface__right_interface_residues": "B:1:G;B:2:G"},
                    {"grain": "interface", "path": str(p2), "assembly_id": "1", "pair": "antibody__antigen", "role_left": "antibody", "role_right": "antigen", "iface__left_interface_residues": "A:1:G;A:2:G", "iface__right_interface_residues": "B:1:G;B:2:G"},
                    {"grain": "interface", "path": str(p3), "assembly_id": "1", "pair": "antibody__antigen", "role_left": "antibody", "role_right": "antigen", "iface__left_interface_residues": "A:1:G;A:2:G", "iface__right_interface_residues": "B:1:G;B:2:G"},
                ]
            ).to_parquet(root / "pdb.parquet", index=False)

            summary = analyze_dataset_outputs(
                root,
                dataset_analyses=("cluster",),
                dataset_analysis_params={"cluster": {"mode": "absolute_interface_ca", "distance_threshold": 0.3}},
            )

            result = read_pdb_grain(root, "interface").sort_values("path").reset_index(drop=True)
            dataset_result = pd.read_parquet(root / "dataset.parquet")

            self.assertEqual(summary["n_cluster_rows"], 3)
            self.assertEqual(summary["n_cluster_dataset_rows"], 0)
            self.assertEqual(summary["n_cluster_pdb_rows"], 3)
            self.assertTrue(dataset_result.empty)

            left_cluster_by_path = dict(zip(result["path"], result["cluster__left_cluster_id"], strict=False))
            right_cluster_by_path = dict(zip(result["path"], result["cluster__right_cluster_id"], strict=False))

            self.assertEqual(result["cluster__left_mode"].dropna().unique().tolist(), ["absolute_interface_ca"])
            self.assertEqual(result["cluster__right_mode"].dropna().unique().tolist(), ["absolute_interface_ca"])
            self.assertEqual(result["cluster__left_interface_side"].dropna().unique().tolist(), ["left"])
            self.assertEqual(result["cluster__right_interface_side"].dropna().unique().tolist(), ["right"])
            self.assertEqual(left_cluster_by_path[str(p1)], left_cluster_by_path[str(p2)])
            self.assertNotEqual(left_cluster_by_path[str(p1)], left_cluster_by_path[str(p3)])
            self.assertEqual(right_cluster_by_path[str(p1)], right_cluster_by_path[str(p3)])
            self.assertNotEqual(right_cluster_by_path[str(p1)], right_cluster_by_path[str(p2)])

    def test_absolute_interface_ca_uses_prepared_path(self) -> None:
        """absolute_interface_ca loads from prepared__path when available (e.g. after superimpose_to_reference)."""
        with tempfile.TemporaryDirectory(prefix="minimum_atw_dataset_cluster_") as tmp_dir:
            root = Path(tmp_dir)
            p1 = root / "source_1.pdb"
            p2 = root / "source_2.pdb"
            # Prepared (globally superimposed) versions: p1_prepared and p2_prepared are close
            p1_prep = root / "prep_1.pdb"
            p2_prep = root / "prep_2.pdb"

            # Source files differ significantly
            _write_pdb(p1, [(0, 0, 0), (2, 0, 0)])
            _write_pdb(p2, [(0, 0, 0), (0, 2, 0)])
            # Prepared files are close to each other
            _write_pdb(p1_prep, [(0, 0, 0), (2, 0, 0)])
            _write_pdb(p2_prep, [(0.1, 0, 0), (2.1, 0, 0)])

            pd.DataFrame(
                [
                    {"grain": "structure", "path": str(p1), "assembly_id": "1", "chain_id": "", "role": "", "pair": "", "role_left": "", "role_right": "", "sub_id": "", "prepared__path": str(p1_prep), "sup__coordinates_applied": True},
                    {"grain": "structure", "path": str(p2), "assembly_id": "1", "chain_id": "", "role": "", "pair": "", "role_left": "", "role_right": "", "sub_id": "", "prepared__path": str(p2_prep), "sup__coordinates_applied": True},
                    {"grain": "interface", "path": str(p1), "assembly_id": "1", "pair": "antibody__antigen", "role_left": "antibody", "role_right": "antigen", "iface__left_interface_residues": "A:1:G;A:2:G"},
                    {"grain": "interface", "path": str(p2), "assembly_id": "1", "pair": "antibody__antigen", "role_left": "antibody", "role_right": "antigen", "iface__left_interface_residues": "A:1:G;A:2:G"},
                ]
            ).to_parquet(root / "pdb.parquet", index=False)

            analyze_dataset_outputs(
                root,
                dataset_analyses=("cluster",),
                dataset_analysis_params={
                    "cluster": {
                        "mode": "absolute_interface_ca",
                        "interface_side": "left",
                        "distance_threshold": 0.3,
                    }
                },
            )

            result = read_pdb_grain(root, "interface").sort_values("path").reset_index(drop=True)
            cluster_ids = result["cluster__default_cluster_id"].dropna().astype(int).tolist()
            # Prepared coords are close → same cluster
            self.assertEqual(len(cluster_ids), 2)
            self.assertEqual(cluster_ids[0], cluster_ids[1])
            self.assertEqual(result["cluster__default_mode"].dropna().unique().tolist(), ["absolute_interface_ca"])

    def test_shape_interface_ca_superimposes_before_chamfer(self) -> None:
        """shape_interface_ca locally superimposes interface Cα (Kabsch) before Chamfer.

        Two structures with the same interface shape but at different positions cluster together.
        A third structure with a different interface shape is in a different cluster.
        """
        with tempfile.TemporaryDirectory(prefix="minimum_atw_shape_cluster_") as tmp_dir:
            root = Path(tmp_dir)
            # p1 and p2: same interface shape (L-shape A:1,A:2), at different absolute positions
            # p3: different interface shape (straight line A:1,A:2)
            p1 = root / "s1.pdb"
            p2 = root / "s2.pdb"
            p3 = root / "s3.pdb"
            _write_pdb(p1, [(0, 0, 0), (2, 0, 0)])          # shape: along x-axis
            _write_pdb(p2, [(10, 10, 10), (12, 10, 10)])    # same shape as p1, translated far away
            _write_pdb(p3, [(0, 0, 0), (0, 2, 0)])          # different shape: along y-axis

            pd.DataFrame(
                [
                    {"grain": "interface", "path": str(p1), "assembly_id": "1", "pair": "ab__ag", "role_left": "ab", "role_right": "ag", "iface__left_interface_residues": "A:1:G;A:2:G"},
                    {"grain": "interface", "path": str(p2), "assembly_id": "1", "pair": "ab__ag", "role_left": "ab", "role_right": "ag", "iface__left_interface_residues": "A:1:G;A:2:G"},
                    {"grain": "interface", "path": str(p3), "assembly_id": "1", "pair": "ab__ag", "role_left": "ab", "role_right": "ag", "iface__left_interface_residues": "A:1:G;A:2:G"},
                ]
            ).to_parquet(root / "pdb.parquet", index=False)

            analyze_dataset_outputs(
                root,
                dataset_analyses=("cluster",),
                dataset_analysis_params={
                    "cluster": {
                        "mode": "shape_interface_ca",
                        "interface_side": "left",
                        "distance_threshold": 0.3,
                    }
                },
            )

            result = read_pdb_grain(root, "interface").sort_values("path").reset_index(drop=True)
            cluster_by_path = dict(zip(result["path"], result["cluster__default_cluster_id"], strict=False))

            # p1 and p2 have the same shape → same cluster after local superimposition
            self.assertEqual(cluster_by_path[str(p1)], cluster_by_path[str(p2)])
            # p3 has a different shape → different cluster
            self.assertNotEqual(cluster_by_path[str(p1)], cluster_by_path[str(p3)])
            self.assertEqual(result["cluster__default_mode"].dropna().unique().tolist(), ["shape_interface_ca"])

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
                    {"grain": "interface", "path": str(p1), "assembly_id": "1", "pair": "antibody__antigen", "role_left": "antibody", "role_right": "antigen", "iface__left_interface_residues": "A:1:G;A:2:G", "iface__right_interface_residues": "B:1:G;B:2:G"},
                    {"grain": "interface", "path": str(p2), "assembly_id": "1", "pair": "antibody__antigen", "role_left": "antibody", "role_right": "antigen", "iface__left_interface_residues": "A:1:G;A:2:G", "iface__right_interface_residues": "B:1:G;B:2:G"},
                    {"grain": "interface", "path": str(p3), "assembly_id": "1", "pair": "antibody__antigen", "role_left": "antibody", "role_right": "antigen", "iface__left_interface_residues": "A:1:G;A:2:G", "iface__right_interface_residues": "B:1:G;B:2:G"},
                ]
            ).to_parquet(root / "pdb.parquet", index=False)

            summary = analyze_dataset_outputs(
                root,
                dataset_analyses=("cluster",),
                dataset_analysis_params={
                    "cluster": {
                        "mode": "absolute_interface_ca",
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
