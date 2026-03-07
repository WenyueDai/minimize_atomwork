from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    import pandas as pd
    import yaml
    from minimum_atw.cli import _load_config
    from minimum_atw.core.pipeline import run_pipeline
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
class InterfaceMetricsPluginTests(unittest.TestCase):
    def test_interface_metrics_plugin_writes_property_columns(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_ifm_test_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            config_path = root / "config.yaml"
            input_dir.mkdir()

            (input_dir / "toy_interface.pdb").write_text(
                textwrap.dedent(
                    """\
                    ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                    ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                    ATOM      3  N   ALA B   2       0.000   0.000   3.000  1.00 20.00           N
                    ATOM      4  CA  ALA B   2       1.200   0.000   3.000  1.00 20.00           C
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
                        "plugins": ["interface_metrics"],
                        "contact_distance": 5.0,
                        "interface_cell_size": 7.5,
                    },
                    sort_keys=False,
                )
            )

            cfg = _load_config(str(config_path))
            run_pipeline(cfg)

            interfaces = read_pdb_grain(out_dir, "interface")
            row = interfaces.iloc[0]

            self.assertEqual(float(row["ifm__contact_distance"]), 5.0)
            self.assertEqual(float(row["ifm__cell_size"]), 7.5)
            self.assertEqual(int(row["ifm__n_residue_contact_pairs"]), 1)
            self.assertEqual(row["ifm__left_interface_residue_labels"], "A:1")
            self.assertEqual(row["ifm__right_interface_residue_labels"], "B:2")
            self.assertEqual(int(row["ifm__left_interface_charge_sum"]), 0)
            self.assertEqual(float(row["ifm__left_interface_glycine_fraction"]), 1.0)
            self.assertEqual(float(row["ifm__right_interface_hydrophobic_fraction"]), 1.0)


if __name__ == "__main__":
    unittest.main()
