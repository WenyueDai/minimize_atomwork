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
    from minimum_atw.plugins.pdb.calculation.interface_analysis.abepitope_score import AbEpiTopeScorePlugin
    from minimum_atw.tests.helpers import read_pdb_grain
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "pydantic", "yaml", "pandas", "pyarrow"}:
        raise
    pd = None
    yaml = None
    _load_config = None
    run_pipeline = None
    AbEpiTopeScorePlugin = None
    read_pdb_grain = None


@unittest.skipIf(run_pipeline is None, "pipeline dependencies are not installed")
class AbEpiTopePluginTests(unittest.TestCase):
    def test_abepitope_plugin_writes_interface_scores(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_abepitope_test_") as tmp_dir:
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
                        "roles": {"antibody": ["A"], "antigen": ["B"]},
                        "interface_pairs": [["antibody", "antigen"]],
                        "plugins": ["abepitope_score"],
                        "abepitope_atom_radius": 4.5,
                    },
                    sort_keys=False,
                )
            )

            cfg = _load_config(str(config_path))
            with (
                patch.object(AbEpiTopeScorePlugin, "available", return_value=(True, "")),
                patch.object(
                    AbEpiTopeScorePlugin,
                    "_run_backend",
                    return_value={"score": 0.75, "target_score": 0.55},
                ),
            ):
                run_pipeline(cfg)

            interfaces = read_pdb_grain(out_dir, "interface")
            row = interfaces.iloc[0]
            self.assertEqual(float(row["abepitope__atom_radius"]), 4.5)
            self.assertEqual(float(row["abepitope__score"]), 0.75)
            self.assertEqual(float(row["abepitope__target_score"]), 0.55)

    def test_abepitope_preflight_requires_hmmsearch(self) -> None:
        plugin = AbEpiTopeScorePlugin()
        with (
            patch("minimum_atw.plugins.pdb.calculation.interface_analysis.abepitope_score.find_spec", return_value=object()),
            patch("minimum_atw.plugins.pdb.calculation.interface_analysis.abepitope_score._resolve_hmmsearch", return_value=None),
        ):
            available, message = plugin.available(None)

        self.assertFalse(available)
        self.assertIn("hmmsearch", message)


if __name__ == "__main__":
    unittest.main()
