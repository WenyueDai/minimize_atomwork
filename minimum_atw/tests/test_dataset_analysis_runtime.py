from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from minimum_atw.plugins.dataset.calculation.runtime import analyze_dataset_outputs
from minimum_atw.tests.helpers import read_dataset_analysis


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

            result = read_dataset_analysis(out_dir, "cdr_entropy")

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

            result = read_dataset_analysis(out_dir, "interface_summary")

            self.assertEqual(summary["dataset_analyses"], "interface_summary")
            self.assertEqual(len(result), 1)
            self.assertEqual(result.iloc[0]["pair"], "vh__antigen")

    def test_runtime_clears_stale_outputs_and_uses_metadata_counts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_dataset_analysis_") as tmp_dir:
            out_dir = Path(tmp_dir)
            analysis_dir = out_dir / "dataset_analysis"
            analysis_dir.mkdir()
            (analysis_dir / "stale.parquet").write_text("old")

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
                    }
                ]
            ).to_parquet(out_dir / "roles.parquet", index=False)
            (out_dir / "run_metadata.json").write_text(
                json.dumps(
                    {
                        "output_kind": "run",
                        "counts": {"interfaces": 7},
                    }
                )
            )

            summary = analyze_dataset_outputs(
                out_dir,
                dataset_analyses=("cdr_entropy",),
            )

            self.assertEqual(summary["n_interfaces"], 7)
            self.assertFalse((analysis_dir / "stale.parquet").exists())
            self.assertTrue((out_dir / "dataset.parquet").exists())

    def test_empty_analysis_does_not_leak_columns_into_dataset_schema(self) -> None:
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
                    }
                ]
            ).to_parquet(out_dir / "roles.parquet", index=False)

            summary = analyze_dataset_outputs(
                out_dir,
                dataset_analyses=("interface_summary", "cdr_entropy"),
                dataset_analysis_params={"cdr_entropy": {"roles": ["missing_role"]}},
            )

            result = pd.read_parquet(out_dir / "dataset.parquet")

            self.assertEqual(summary["n_cdr_entropy_rows"], 0)
            self.assertEqual(result["analysis"].unique().tolist(), ["interface_summary"])
            self.assertNotIn("region", result.columns)
            self.assertNotIn("shannon_entropy", result.columns)

    def test_cleanup_prepared_outputs_after_success_when_requested(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_dataset_analysis_") as tmp_dir:
            out_dir = Path(tmp_dir)
            prepared_dir = out_dir / "_prepared"
            prepared_dir.mkdir()
            (prepared_dir / "marker.txt").write_text("keep until analysis succeeds")

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
                cleanup_prepared_after_dataset_analysis=True,
            )

            result = read_dataset_analysis(out_dir, "interface_summary")
            self.assertEqual(len(result), 1)
            self.assertEqual(summary["cleaned_prepared_outputs"], 1)
            self.assertFalse(prepared_dir.exists())


if __name__ == "__main__":
    unittest.main()
