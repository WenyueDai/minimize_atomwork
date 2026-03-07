from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    import pandas as pd
    import yaml
    from minimum_atw.cli import _load_config
    from minimum_atw.core.output_files import dataset_output_path, pdb_output_path, read_output_metadata
    from minimum_atw.core.pipeline import prepare_outputs, run_pipeline, run_plugin, run_plugins
    from minimum_atw.tests.helpers import read_pdb_grain
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "pydantic", "yaml", "pandas", "pyarrow"}:
        raise
    pd = None
    yaml = None
    _load_config = None
    run_pipeline = None
    read_pdb_grain = None


@unittest.skipIf(run_pipeline is None, "pipeline dependencies are not installed")
class IntegrationSmokeTests(unittest.TestCase):
    def test_run_pipeline_respects_custom_output_filenames(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_test_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            config_path = root / "config.yaml"
            input_dir.mkdir()

            (input_dir / "toy_complex.pdb").write_text(
                textwrap.dedent(
                    """\
                    ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                    ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                    ATOM      3  N   GLY B   1       0.000   0.000   3.000  1.00 20.00           N
                    ATOM      4  CA  GLY B   1       1.200   0.000   3.000  1.00 20.00           C
                    TER
                    END
                    """
                )
            )

            config_path.write_text(
                yaml.safe_dump(
                    {
                        "input_dir": str(input_dir),
                        "out_dir": str(out_dir),
                        "roles": {"binder": ["A"], "target": ["B"]},
                        "interface_pairs": [["binder", "target"]],
                        "plugins": ["identity"],
                        "dataset_analyses": ["interface_summary"],
                        "pdb_output_name": "20250212_pdb.parquet",
                        "dataset_output_name": "20250212_dataset.parquet",
                    },
                    sort_keys=False,
                )
            )

            cfg = _load_config(str(config_path))
            counts = run_pipeline(cfg)
            metadata = json.loads((out_dir / "run_metadata.json").read_text())
            resolved_metadata = read_output_metadata(out_dir)

            self.assertEqual(counts["structures"], 1)
            self.assertFalse((out_dir / "pdb.parquet").exists())
            self.assertFalse((out_dir / "dataset.parquet").exists())
            self.assertTrue(pdb_output_path(out_dir, metadata=resolved_metadata).exists())
            self.assertTrue(dataset_output_path(out_dir, metadata=resolved_metadata).exists())
            self.assertEqual(
                metadata["output_files"],
                {
                    "pdb": "20250212_pdb.parquet",
                    "dataset": "20250212_dataset.parquet",
                },
            )

    def test_clean_run_omits_top_level_plugin_status_but_keeps_summary_in_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_test_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            config_path = root / "config.yaml"
            input_dir.mkdir()

            (input_dir / "toy_complex.pdb").write_text(
                textwrap.dedent(
                    """\
                    ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                    ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                    TER
                    END
                    """
                )
            )

            config_path.write_text(
                yaml.safe_dump(
                    {
                        "input_dir": str(input_dir),
                        "out_dir": str(out_dir),
                        "roles": {"binder": ["A"]},
                        "plugins": ["identity"],
                    },
                    sort_keys=False,
                )
            )

            cfg = _load_config(str(config_path))
            counts = run_pipeline(cfg)
            metadata = json.loads((out_dir / "run_metadata.json").read_text())

            self.assertEqual(counts["structures"], 1)
            self.assertFalse((out_dir / "plugin_status.parquet").exists())
            self.assertEqual(metadata["counts"]["status"], 1)
            self.assertEqual(metadata["status_summary"], {"ok": 1})

    def test_identity_pipeline_writes_expected_tables(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_test_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            config_path = root / "config.yaml"
            input_dir.mkdir()

            (input_dir / "toy_complex.pdb").write_text(
                textwrap.dedent(
                    """\
                    ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                    ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                    ATOM      3  N   GLY B   1       0.000   0.000   3.000  1.00 20.00           N
                    ATOM      4  CA  GLY B   1       1.200   0.000   3.000  1.00 20.00           C
                    TER
                    END
                    """
                )
            )

            config_path.write_text(
                yaml.safe_dump(
                    {
                        "input_dir": str(input_dir),
                        "out_dir": str(out_dir),
                        "roles": {"binder": ["A"], "target": ["B"]},
                        "interface_pairs": [["binder", "target"]],
                        "plugins": ["identity"],
                        "keep_intermediate_outputs": True,
                        "dataset_annotations": {"dataset_id": "toy_run", "project": "smoke"},
                    },
                    sort_keys=False,
                )
            )

            cfg = _load_config(str(config_path))
            counts = run_pipeline(cfg)

            self.assertEqual(counts["structures"], 1)
            self.assertEqual(counts["chains"], 2)
            self.assertEqual(counts["roles"], 2)
            self.assertEqual(counts["interfaces"], 1)

            structures = read_pdb_grain(out_dir, "structure")
            chains = read_pdb_grain(out_dir, "chain")
            roles = read_pdb_grain(out_dir, "role")
            interfaces = read_pdb_grain(out_dir, "interface")
            metadata = json.loads((out_dir / "run_metadata.json").read_text())

            self.assertEqual(len(structures), 1)
            self.assertEqual(len(chains), 2)
            self.assertEqual(len(roles), 2)
            self.assertEqual(len(interfaces), 1)
            self.assertIn("id__n_atoms_total", structures.columns)
            self.assertIn("dataset__id", structures.columns)
            self.assertIn("dataset__name", structures.columns)
            self.assertIn("source__name", structures.columns)
            self.assertIn("source__format", structures.columns)
            self.assertIn("source__size_bytes", structures.columns)
            self.assertIn("source__n_atoms_loaded", structures.columns)
            self.assertIn("id__n_atoms", chains.columns)
            self.assertIn("id__n_atoms", roles.columns)
            self.assertEqual(structures.iloc[0]["source__name"], "toy_complex.pdb")
            self.assertEqual(structures.iloc[0]["source__format"], "pdb")
            self.assertEqual(str(structures.iloc[0]["dataset__id"]), "toy_run")
            self.assertEqual(str(structures.iloc[0]["dataset__name"]), "toy_run")
            self.assertEqual(int(structures.iloc[0]["source__n_atoms_loaded"]), 4)
            self.assertEqual(int(structures.iloc[0]["source__n_chains_loaded"]), 2)
            self.assertEqual(metadata["output_kind"], "run")
            self.assertEqual(metadata["counts"]["structures"], 1)
            self.assertEqual(metadata["status_summary"], {"ok": 1})
            self.assertEqual(metadata["config"]["plugins"], ["identity"])
            self.assertEqual(metadata["merge_compatibility"]["plugins"], ["identity"])
            self.assertIn("pdb", metadata["table_columns"])
            self.assertIn("id__n_atoms_total", metadata["table_columns"]["pdb"])
            self.assertFalse((out_dir / "bad_files.parquet").exists())
            self.assertTrue((out_dir / "plugin_status.parquet").exists())

            self.assertTrue((out_dir / "_plugins" / "identity.pdb.parquet").exists())
            manifest = pd.read_parquet(out_dir / "_prepared" / "prepared_manifest.parquet")
            self.assertEqual(manifest.iloc[0]["source_name"], "toy_complex.pdb")
            self.assertEqual(manifest.iloc[0]["source_format"], "pdb")
            self.assertEqual(int(manifest.iloc[0]["n_atoms_loaded"]), 4)
            self.assertEqual(int(manifest.iloc[0]["n_chains_loaded"]), 2)

            # simulate a later resume with checkpointing enabled
            input2 = input_dir / "toy_complex2.pdb"
            input2.write_text(input_dir.joinpath("toy_complex.pdb").read_text())
            cfg2 = _load_config(str(config_path))
            cfg2 = cfg2.model_copy(update={"checkpoint_enabled": True})
            counts2 = run_pipeline(cfg2)

            self.assertEqual(counts2["structures"], 2)
            resumed_structures = read_pdb_grain(out_dir, "structure")
            self.assertEqual(len(resumed_structures), 2)

    def test_checkpoint_allows_plugin_resume(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_test_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            config_path = root / "config.yaml"
            input_dir.mkdir()

            # write two structures, but we will run plugin only after preparing
            for i in (1, 2):
                (input_dir / f"toy_{i}.pdb").write_text(
                    textwrap.dedent(
                        """\
                        ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                        ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                        TER
                        END
                        """
                    )
                )

            config_path.write_text(
                yaml.safe_dump(
                    {
                        "input_dir": str(input_dir),
                        "out_dir": str(out_dir),
                        "roles": {"binder": ["A"]},
                        "interface_pairs": [],
                        "plugins": ["identity"],
                        "keep_intermediate_outputs": True,
                    },
                    sort_keys=False,
                )
            )

            cfg = _load_config(str(config_path))
            # run prepare first with checkpointing enabled so manifest is written
            cfg = cfg.model_copy(update={"checkpoint_enabled": True})
            prepare_counts = run_pipeline(cfg)
            # plugin results exist for one structure (first run)
            first_status = pd.read_parquet(out_dir / "_plugins" / "identity.plugin_status.parquet")
            self.assertEqual(len(first_status), 2)

            # now add a third structure and resume only plugin stage
            (input_dir / "toy_3.pdb").write_text(
                (input_dir / "toy_1.pdb").read_text()
            )
            # re-prepare only new structure
            counts_prep2 = prepare_outputs(cfg)
            self.assertEqual(counts_prep2["structures"], 3)

            # run plugin again, checkpointing should skip already processed entries
            plugin_counts2 = run_plugin(cfg, "identity")
            # expect exactly one new status row added (third structure)
            new_status = pd.read_parquet(out_dir / "_plugins" / "identity.plugin_status.parquet")
            self.assertEqual(len(new_status), 3)

    def test_run_plugins_runs_multiple_plugins_incrementally(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_test_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            config_path = root / "config.yaml"
            input_dir.mkdir()

            (input_dir / "toy_complex.pdb").write_text(
                textwrap.dedent(
                    """\
                    ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                    ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                    ATOM      3  N   GLY B   1       0.000   0.000   3.000  1.00 20.00           N
                    ATOM      4  CA  GLY B   1       1.200   0.000   3.000  1.00 20.00           C
                    TER
                    END
                    """
                )
            )

            config_path.write_text(
                yaml.safe_dump(
                    {
                        "input_dir": str(input_dir),
                        "out_dir": str(out_dir),
                        "roles": {"binder": ["A"], "target": ["B"]},
                        "interface_pairs": [["binder", "target"]],
                        "plugins": ["identity"],  # config has one plugin but we'll run multiple
                        "keep_intermediate_outputs": True,
                    },
                    sort_keys=False,
                )
            )

            cfg = _load_config(str(config_path))
            # First prepare the structures
            prepare_counts = run_pipeline(cfg)
            self.assertEqual(prepare_counts["structures"], 1)

            # Now run multiple plugins incrementally
            plugins_counts = run_plugins(cfg, ["identity"])  # Just one for now, but testing the API
            self.assertEqual(plugins_counts["structures"], 1)
            self.assertEqual(plugins_counts["chains"], 2)
            self.assertEqual(plugins_counts["roles"], 2)
            self.assertEqual(plugins_counts["interfaces"], 1)

            # Check that plugin outputs exist
            self.assertTrue((out_dir / "_plugins" / "identity.pdb.parquet").exists())



if __name__ == "__main__":
    unittest.main()
