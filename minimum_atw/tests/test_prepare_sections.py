from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    import pandas as pd
    import yaml
    from minimum_atw.core.config import Config
    from minimum_atw.core.pipeline import _prepare_execution_metadata, run_pipeline
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "pydantic", "yaml", "pandas", "pyarrow"}:
        raise
    pd = None
    yaml = None
    Config = None
    _prepare_execution_metadata = None
    run_pipeline = None


@unittest.skipIf(run_pipeline is None, "pipeline dependencies are not installed")
class PrepareSectionsTests(unittest.TestCase):
    def test_legacy_manipulations_are_routed_by_prepare_section(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            manipulations=["chain_continuity", "center_on_origin", "superimpose_homology"],
        )

        metadata = _prepare_execution_metadata(cfg)
        self.assertEqual(metadata["sections"]["quality_control"], ["chain_continuity"])
        self.assertEqual(metadata["sections"]["structure"], ["center_on_origin"])
        self.assertEqual(metadata["sections"]["dataset"], ["superimpose_homology"])

    def test_quality_control_stage_writes_continuity_and_clash_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_prepare_qc_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            config_path = root / "config.yaml"
            input_dir.mkdir()

            (input_dir / "toy_qc.pdb").write_text(
                textwrap.dedent(
                    """\
                    ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                    ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                    ATOM      3  C   GLY A   1       2.400   0.000   0.000  1.00 20.00           C
                    ATOM      4  N   GLY A   3       5.000   0.000   0.000  1.00 20.00           N
                    ATOM      5  CA  GLY A   3       6.200   0.000   0.000  1.00 20.00           C
                    ATOM      6  C   GLY A   3       7.400   0.000   0.000  1.00 20.00           C
                    ATOM      7  N   ALA B   1       5.200   0.000   0.000  1.00 20.00           N
                    ATOM      8  CA  ALA B   1       6.400   0.000   0.000  1.00 20.00           C
                    ATOM      9  C   ALA B   1       7.600   0.000   0.000  1.00 20.00           C
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
                        "quality_controls": ["chain_continuity", "structure_clashes"],
                        "plugins": [],
                    },
                    sort_keys=False,
                )
            )

            cfg = Config(**yaml.safe_load(config_path.read_text()))
            run_pipeline(cfg)

            structures = pd.read_parquet(out_dir / "structures.parquet")
            chains = pd.read_parquet(out_dir / "chains.parquet")

            self.assertTrue(bool(structures.iloc[0]["clash__has_clash"]))
            self.assertGreater(int(structures.iloc[0]["clash__n_clashing_atom_pairs"]), 0)

            chain_a = chains[chains["chain_id"] == "A"].iloc[0]
            self.assertTrue(bool(chain_a["continuity__has_break"]))
            self.assertGreaterEqual(int(chain_a["continuity__n_breaks"]), 1)


if __name__ == "__main__":
    unittest.main()
