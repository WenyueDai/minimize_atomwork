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
    from minimum_atw.core.pipeline import prepare_outputs, run_pipeline, run_plugin, run_plugins
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "pydantic", "yaml", "pandas", "pyarrow"}:
        raise
    pd = None
    yaml = None
    _load_config = None
    run_pipeline = None


@unittest.skipIf(run_pipeline is None, "pipeline dependencies are not installed")
class IntegrationSmokeTests(unittest.TestCase):
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

            structures = pd.read_parquet(out_dir / "structures.parquet")
            chains = pd.read_parquet(out_dir / "chains.parquet")
            roles = pd.read_parquet(out_dir / "roles.parquet")
            interfaces = pd.read_parquet(out_dir / "interfaces.parquet")
            metadata = json.loads((out_dir / "run_metadata.json").read_text())

            self.assertEqual(len(structures), 1)
            self.assertEqual(len(chains), 2)
            self.assertEqual(len(roles), 2)
            self.assertEqual(len(interfaces), 1)
            self.assertIn("id__n_atoms_total", structures.columns)
            self.assertIn("id__n_atoms", chains.columns)
            self.assertIn("id__n_atoms", roles.columns)
            self.assertEqual(metadata["output_kind"], "run")
            self.assertEqual(metadata["counts"]["structures"], 1)
            self.assertEqual(metadata["config"]["plugins"], ["identity"])
            self.assertEqual(metadata["merge_compatibility"]["plugins"], ["identity"])
            self.assertIn("structures", metadata["table_columns"])
            self.assertIn("id__n_atoms_total", metadata["table_columns"]["structures"])

            identity_plugin_dir = out_dir / "_plugins" / "identity"
            self.assertTrue((identity_plugin_dir / "structures.parquet").exists())
            self.assertTrue((identity_plugin_dir / "chains.parquet").exists())
            self.assertTrue((identity_plugin_dir / "roles.parquet").exists())
            self.assertFalse((identity_plugin_dir / "interfaces.parquet").exists())

            # simulate a later resume with checkpointing enabled
            input2 = input_dir / "toy_complex2.pdb"
            input2.write_text(input_dir.joinpath("toy_complex.pdb").read_text())
            cfg2 = _load_config(str(config_path))
            cfg2 = cfg2.model_copy(update={"checkpoint_enabled": True})
            counts2 = run_pipeline(cfg2)

            self.assertEqual(counts2["structures"], 2)
            resumed_structures = pd.read_parquet(out_dir / "structures.parquet")
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
            identity_plugin_dir = out_dir / "_plugins" / "identity"
            first_status = pd.read_parquet(identity_plugin_dir / "plugin_status.parquet")
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
            new_status = pd.read_parquet(identity_plugin_dir / "plugin_status.parquet")
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
            identity_plugin_dir = out_dir / "_plugins" / "identity"
            self.assertTrue((identity_plugin_dir / "structures.parquet").exists())
            self.assertTrue((identity_plugin_dir / "chains.parquet").exists())
            self.assertTrue((identity_plugin_dir / "roles.parquet").exists())
            self.assertFalse((identity_plugin_dir / "interfaces.parquet").exists())  # identity plugin doesn't emit interfaces



if __name__ == "__main__":
    unittest.main()
