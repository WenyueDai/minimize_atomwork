from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from minimum_atw.plugins.dataset_analysis.runtime import analyze_dataset_outputs


class DatasetAnalysisRuntimeTests(unittest.TestCase):
    def test_runtime_passes_params_to_each_analysis_directly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_dataset_analysis_") as tmp_dir:
            out_dir = Path(tmp_dir)
            pd.DataFrame(
                [
                    {
                        "path": "/tmp/example_1.pdb",
                        "assembly_id": "1",
                        "pair": "vh__antigen",
                        "role_left": "vh",
                        "role_right": "antigen",
                    }
                ]
            ).to_parquet(out_dir / "interfaces.parquet", index=False)
            pd.DataFrame(
                [
                    {
                        "path": "/tmp/example_1.pdb",
                        "assembly_id": "1",
                        "role": "vh",
                        "abseq__cdr1_sequence": "AAA",
                        "abseq__cdr2_sequence": "BBB",
                        "abseq__cdr3_sequence": "CCC",
                        "rolseq__sequence": "AAABBBCCC",
                    },
                    {
                        "path": "/tmp/example_2.pdb",
                        "assembly_id": "1",
                        "role": "vh",
                        "abseq__cdr1_sequence": "AAA",
                        "abseq__cdr2_sequence": "BBD",
                        "abseq__cdr3_sequence": "CCD",
                        "rolseq__sequence": "AAABBDCCD",
                    },
                    {
                        "path": "/tmp/example_3.pdb",
                        "assembly_id": "1",
                        "role": "vl",
                        "abseq__cdr1_sequence": "EEE",
                        "abseq__cdr2_sequence": "FFF",
                        "abseq__cdr3_sequence": "GGG",
                        "rolseq__sequence": "EEEFFFGGG",
                    },
                ]
            ).to_parquet(out_dir / "roles.parquet", index=False)

            summary = analyze_dataset_outputs(
                out_dir,
                dataset_analyses=("cdr_entropy",),
                dataset_analysis_params={
                    "cdr_entropy": {
                        "roles": ["vh"],
                        "regions": ["cdr3"],
                    }
                },
            )

            result = pd.read_parquet(out_dir / "dataset_analysis" / "cdr_entropy.parquet")

            self.assertEqual(summary["dataset_analyses"], "cdr_entropy")
            self.assertEqual(len(result), 1)
            self.assertEqual(result.iloc[0]["role"], "vh")
            self.assertEqual(result.iloc[0]["region"], "cdr3")

    def test_runtime_can_project_missing_interface_metric_columns(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_dataset_analysis_") as tmp_dir:
            out_dir = Path(tmp_dir)
            pd.DataFrame(
                [
                    {
                        "path": "/tmp/example_1.pdb",
                        "assembly_id": "1",
                        "pair": "vh__antigen",
                        "role_left": "vh",
                        "role_right": "antigen",
                    }
                ]
            ).to_parquet(out_dir / "interfaces.parquet", index=False)

            summary = analyze_dataset_outputs(
                out_dir,
                dataset_analyses=("interface_summary",),
            )

            result = pd.read_parquet(out_dir / "dataset_analysis" / "interface_summary.parquet")

            self.assertEqual(summary["dataset_analyses"], "interface_summary")
            self.assertEqual(len(result), 1)
            self.assertEqual(result.iloc[0]["pair"], "vh__antigen")


if __name__ == "__main__":
    unittest.main()
