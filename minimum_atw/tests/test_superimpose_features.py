from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    import pandas as pd
    from biotite.structure.io import load_structure

    from minimum_atw.core.config import Config
    from minimum_atw.core.pipeline import prepare_outputs, run_pipeline
    from minimum_atw.plugins.dataset.calculation.runtime import analyze_dataset_outputs
    from minimum_atw.tests.helpers import read_pdb_grain
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "numpy", "pandas", "pydantic", "pyarrow"}:
        raise
    pd = None
    load_structure = None
    Config = None
    prepare_outputs = None
    run_pipeline = None
    analyze_dataset_outputs = None
    read_pdb_grain = None


def _write_pdb(
    path: Path,
    chain_a_coords: list[tuple[float, float, float]],
    chain_b_coords: list[tuple[float, float, float]] | None = None,
    chain_c_coords: list[tuple[float, float, float]] | None = None,
) -> None:
    chain_b_coords = chain_b_coords or []
    chain_c_coords = chain_c_coords or []
    lines: list[str] = []
    atom_id = 1
    for chain_id, coords in (("A", chain_a_coords), ("B", chain_b_coords), ("C", chain_c_coords)):
        for res_id, (x, y, z) in enumerate(coords, start=1):
            lines.append(
                f"ATOM  {atom_id:5d}  CA  GLY {chain_id}{res_id:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C"
            )
            atom_id += 1
    lines.extend(["TER", "END"])
    path.write_text("\n".join(lines) + "\n")


@unittest.skipIf(run_pipeline is None or Config is None, "superimpose feature dependencies are not installed")
class SuperimposeFeatureTests(unittest.TestCase):
    def test_prepare_superimpose_manipulation_writes_transformed_prepared_structure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_prepare_superimpose_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            input_dir.mkdir()

            reference = input_dir / "ref.pdb"
            mobile = input_dir / "mobile.pdb"
            _write_pdb(
                reference,
                chain_a_coords=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
                chain_b_coords=[(10.0, 0.0, 0.0)],
                chain_c_coords=[(10.0, 2.0, 0.0)],
            )
            _write_pdb(
                mobile,
                chain_a_coords=[(20.0, 5.0, 0.0), (22.0, 5.0, 0.0)],
                chain_b_coords=[(30.0, 5.0, 0.0)],
                chain_c_coords=[(30.0, 7.0, 0.0)],
            )

            cfg = Config(
                input_dir=str(input_dir),
                out_dir=str(out_dir),
                roles={"antigen": ["A"], "vl": ["B"], "vh": ["C"], "antibody": ["B", "C"]},
                interface_pairs=[("antibody", "antigen")],
                manipulations=[{"name": "superimpose_to_reference", "grain": "pdb"}],
                keep_prepared_structures=True,
                plugin_params={
                    "superimpose_to_reference": {
                        "reference_path": str(reference),
                        "on_chains": ["A"],
                    }
                },
            )

            prepare_outputs(cfg)

            manifest = pd.read_parquet(out_dir / "_prepared" / "prepared_manifest.parquet")
            mobile_prepared_path = Path(
                manifest.loc[manifest["path"].astype(str) == str(mobile.resolve()), "prepared_path"].iloc[0]
            )
            prepared_mobile = load_structure(mobile_prepared_path)
            prepared_a = prepared_mobile[prepared_mobile.chain_id.astype(str) == "A"]

            self.assertTrue(mobile_prepared_path.exists())
            self.assertAlmostEqual(float(prepared_a.coord[0][0]), 0.0, places=3)
            self.assertAlmostEqual(float(prepared_a.coord[1][0]), 2.0, places=3)

            structures = pd.read_parquet(out_dir / "_prepared" / "pdb.parquet")
            structures = structures[structures["grain"].astype(str) == "structure"].reset_index(drop=True)
            mobile_row = structures[structures["path"].astype(str) == str(mobile.resolve())].iloc[0]
            self.assertIn("prepared__path", structures.columns)
            self.assertIn("sup__reference_path", structures.columns)
            self.assertTrue(bool(mobile_row["sup__coordinates_applied"]))
            self.assertEqual(str(mobile_row["prepared__path"]), str(mobile_prepared_path.resolve()))

    def test_run_pipeline_copies_prepared_and_persisted_superimposed_structures_to_final_out_dir(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_superimpose_copy_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            input_dir.mkdir()

            reference = input_dir / "ref.pdb"
            mobile = input_dir / "mobile.pdb"
            _write_pdb(reference, chain_a_coords=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])
            _write_pdb(mobile, chain_a_coords=[(10.0, 0.0, 0.0), (12.0, 0.0, 0.0)])

            cfg = Config(
                input_dir=str(input_dir),
                out_dir=str(out_dir),
                roles={},
                interface_pairs=[],
                plugins=["identity", "structure_rmsd"],
                keep_prepared_structures=True,
                plugin_params={
                    "structure_rmsd": {
                        "reference_path": str(reference),
                        "on_chains": ["A"],
                        "persist_transformed_structures": True,
                    }
                },
            )

            run_pipeline(cfg)

            self.assertTrue((out_dir / "_prepared" / "prepared_manifest.parquet").exists())
            structures = read_pdb_grain(out_dir, "structure")
            mobile_row = structures[structures["path"].astype(str) == str(mobile.resolve())].iloc[0]
            transformed_path = Path(str(mobile_row["rmsd__transformed_path"]))
            prepared_path = Path(str(mobile_row["prepared__path"]))

            self.assertTrue(transformed_path.exists())
            self.assertTrue(prepared_path.exists())
            self.assertTrue(str(transformed_path).startswith(str(out_dir.resolve())))
            self.assertTrue(str(prepared_path).startswith(str(out_dir.resolve())))

    def test_cluster_absolute_interface_ca_uses_prepared_paths(self) -> None:
        """absolute_interface_ca reads from prepared__path (globally superimposed structures).

        Source files p1/p2 differ significantly, but their prepared (superimposed) versions
        prep1/prep2 are close → they end up in the same cluster.
        """
        with tempfile.TemporaryDirectory(prefix="minimum_atw_cluster_absolute_") as tmp_dir:
            out_dir = Path(tmp_dir)
            p1 = out_dir / "source_1.pdb"
            p2 = out_dir / "source_2.pdb"
            prep1 = out_dir / "prepared_1.pdb"
            prep2 = out_dir / "prepared_2.pdb"

            # Source: very different shapes
            _write_pdb(p1, chain_a_coords=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])
            _write_pdb(p2, chain_a_coords=[(0.0, 0.0, 0.0), (0.0, 2.0, 0.0)])
            # Prepared (after superimpose_to_reference): nearly identical → same cluster
            _write_pdb(prep1, chain_a_coords=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])
            _write_pdb(prep2, chain_a_coords=[(0.1, 0.0, 0.0), (2.1, 0.0, 0.0)])

            pd.DataFrame(
                [
                    {
                        "path": str(p1.resolve()),
                        "assembly_id": "1",
                        "grain": "structure",
                        "chain_id": "",
                        "role": "",
                        "pair": "",
                        "role_left": "",
                        "role_right": "",
                        "sub_id": "",
                        "prepared__path": str(prep1.resolve()),
                        "sup__coordinates_applied": True,
                    },
                    {
                        "path": str(p2.resolve()),
                        "assembly_id": "1",
                        "grain": "structure",
                        "chain_id": "",
                        "role": "",
                        "pair": "",
                        "role_left": "",
                        "role_right": "",
                        "sub_id": "",
                        "prepared__path": str(prep2.resolve()),
                        "sup__coordinates_applied": True,
                    },
                    {
                        "path": str(p1.resolve()),
                        "assembly_id": "1",
                        "grain": "interface",
                        "chain_id": "",
                        "role": "",
                        "pair": "antibody__antigen",
                        "role_left": "antibody",
                        "role_right": "antigen",
                        "sub_id": "",
                        "iface__left_interface_residues": "A:1:G;A:2:G",
                    },
                    {
                        "path": str(p2.resolve()),
                        "assembly_id": "1",
                        "grain": "interface",
                        "chain_id": "",
                        "role": "",
                        "pair": "antibody__antigen",
                        "role_left": "antibody",
                        "role_right": "antigen",
                        "sub_id": "",
                        "iface__left_interface_residues": "A:1:G;A:2:G",
                    },
                ]
            ).to_parquet(out_dir / "pdb.parquet", index=False)
            (out_dir / "dataset_metadata.json").write_text(
                json.dumps(
                    {
                        "output_kind": "dataset",
                        "output_files": {"pdb": "pdb.parquet", "dataset": "dataset.parquet"},
                        "counts": {"interfaces": 2},
                    }
                )
            )

            analyze_dataset_outputs(
                out_dir,
                dataset_analyses=("cluster",),
                dataset_analysis_params={
                    "cluster": {
                        "mode": "absolute_interface_ca",
                        "interface_side": "left",
                        "distance_threshold": 0.3,
                    }
                },
            )

            result = read_pdb_grain(out_dir, "interface").sort_values("path").reset_index(drop=True)
            cluster_ids = result["cluster__default_cluster_id"].dropna().astype(int).tolist()
            self.assertEqual(len(cluster_ids), 2)
            self.assertEqual(cluster_ids[0], cluster_ids[1])
            self.assertEqual(result["cluster__default_mode"].dropna().unique().tolist(), ["absolute_interface_ca"])


if __name__ == "__main__":
    unittest.main()
