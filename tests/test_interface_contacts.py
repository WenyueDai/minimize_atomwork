from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

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
class InterfaceContactsTests(unittest.TestCase):
    def test_interface_residue_columns_are_split_and_include_residue_names(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_iface_test_") as tmp_dir:
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
                        "plugins": ["interface_contacts"],
                        "contact_distance": 5.0,
                    },
                    sort_keys=False,
                )
            )

            cfg = _load_config(str(config_path))
            run_pipeline(cfg)

            interfaces = pd.read_parquet(out_dir / "interfaces.parquet")

            self.assertIn("iface__left_interface_residues", interfaces.columns)
            self.assertIn("iface__right_interface_residues", interfaces.columns)
            self.assertNotIn("iface__interface_payload", interfaces.columns)
            self.assertEqual(interfaces.iloc[0]["iface__left_interface_residues"], "A:1:G")
            self.assertEqual(interfaces.iloc[0]["iface__right_interface_residues"], "B:2:A")

    def test_antibody_interface_rows_include_cdr_contact_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_iface_cdr_test_") as tmp_dir:
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
                        "roles": {"vh": ["A"], "antigen": ["B"]},
                        "interface_pairs": [["vh", "antigen"]],
                        "plugins": ["interface_contacts"],
                        "numbering_roles": ["vh"],
                        "contact_distance": 5.0,
                    },
                    sort_keys=False,
                )
            )

            cfg = _load_config(str(config_path))
            with (
                patch(
                    "minimum_atw.plugins.interface_analysis.interface_contacts.antibody_role_sequences",
                    return_value=[("vh", ["A"], "G")],
                ),
                patch(
                    "minimum_atw.plugins.interface_analysis.interface_contacts.cdr_indices",
                    return_value={"cdr1": [0], "cdr2": [], "cdr3": []},
                ),
            ):
                run_pipeline(cfg)

            interfaces = pd.read_parquet(out_dir / "interfaces.parquet")

            self.assertEqual(int(interfaces.iloc[0]["iface__n_left_vh_cdr1_interface_residues"]), 1)
            self.assertEqual(interfaces.iloc[0]["iface__left_vh_cdr1_interface_residues"], "A:1:G")
            self.assertEqual(int(interfaces.iloc[0]["iface__n_left_vh_cdr2_interface_residues"]), 0)
            self.assertEqual(interfaces.iloc[0]["iface__left_vh_cdr2_interface_residues"], "")


if __name__ == "__main__":
    unittest.main()
