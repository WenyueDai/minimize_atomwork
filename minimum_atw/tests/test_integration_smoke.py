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
    from minimum_atw.core.pipeline import run_pipeline
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


if __name__ == "__main__":
    unittest.main()
