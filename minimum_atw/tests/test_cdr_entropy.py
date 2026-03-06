from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from minimum_atw.plugins.dataset_analysis.base import DatasetAnalysisContext
from minimum_atw.plugins.dataset_analysis.cdr_entropy import CDREntropyPlugin


def _ctx(tmp_dir: str, params: dict[str, object] | None = None) -> DatasetAnalysisContext:
    return DatasetAnalysisContext(
        out_dir=Path(tmp_dir),
        analysis_dir=Path(tmp_dir),
        df_interfaces=pd.DataFrame(),
        df_roles=pd.DataFrame(
            [
                {
                    "role": "vh",
                    "abseq__cdr1_sequence": "AAA",
                    "abseq__cdr2_sequence": "BBB",
                    "abseq__cdr3_sequence": "CCC",
                    "rolseq__sequence": "AAABBBCCC",
                },
                {
                    "role": "vh",
                    "abseq__cdr1_sequence": "AAA",
                    "abseq__cdr2_sequence": "BBD",
                    "abseq__cdr3_sequence": "CCD",
                    "rolseq__sequence": "AAABBDCCD",
                },
                {
                    "role": "vl",
                    "abseq__cdr1_sequence": "EEE",
                    "abseq__cdr2_sequence": "FFF",
                    "abseq__cdr3_sequence": "GGG",
                    "rolseq__sequence": "EEEFFFGGG",
                },
            ]
        ),
        params=params or {},
        annotations={},
    )


class CDREntropyTests(unittest.TestCase):
    def test_default_runs_all_cdrs_for_all_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = CDREntropyPlugin()
            plugin.run(_ctx(tmp_dir))

            out = pd.read_parquet(Path(tmp_dir) / "cdr_entropy.parquet")

            self.assertEqual(sorted(out["role"].unique().tolist()), ["vh", "vl"])
            self.assertEqual(sorted(out["region"].unique().tolist()), ["cdr1", "cdr2", "cdr3"])
            self.assertEqual(len(out), 6)

    def test_can_select_single_role_and_single_cdr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = CDREntropyPlugin()
            plugin.run(
                _ctx(
                    tmp_dir,
                    params={
                        "roles": ["vh"],
                        "regions": ["cdr3"],
                    },
                )
            )

            out = pd.read_parquet(Path(tmp_dir) / "cdr_entropy.parquet")

            self.assertEqual(len(out), 1)
            self.assertEqual(out.iloc[0]["role"], "vh")
            self.assertEqual(out.iloc[0]["region"], "cdr3")
            self.assertEqual(out.iloc[0]["source_column"], "abseq__cdr3_sequence")

    def test_can_select_full_sequence_entropy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = CDREntropyPlugin()
            plugin.run(
                _ctx(
                    tmp_dir,
                    params={
                        "roles": ["vh"],
                        "regions": ["sequence"],
                    },
                )
            )

            out = pd.read_parquet(Path(tmp_dir) / "cdr_entropy.parquet")

            self.assertEqual(len(out), 1)
            self.assertEqual(out.iloc[0]["region"], "sequence")
            self.assertEqual(out.iloc[0]["cdr"], "")
            self.assertEqual(out.iloc[0]["source_column"], "rolseq__sequence")
            self.assertEqual(int(out.iloc[0]["n_sequences"]), 2)


if __name__ == "__main__":
    unittest.main()
