from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from minimum_atw.plugins.dataset.calculation.base import DatasetAnalysisContext
from minimum_atw.plugins.dataset.calculation.cdr_entropy import CDREntropyPlugin


VH_SEQ_A = "EVQLVESGGGLVQPGGSLRLSCAASGFTFSSYAMSWVRQAPGKGLEWVSAISSGGGNTYYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCARDRGGYFDYWGQGTLVTVSS"
VH_SEQ_B = "EVQLVESGGGLVQPGGSLRLSCAASGFTFSSYAMSWVRQAPGKGLEWVSAISSGGSNTYYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCARDRGGYFDYWGQGTLVTVSS"
VL_SEQ_A = "DIQMTQSPSSLSASVGDRVTITCRASQSISSSLAWYQQKPGKAPKLLIYDASSLESGVPSRFSGSGSGTDFTLTISSLQPEDFATYYCQQYNSYPWTFGQGTKVEIK"


def _ctx(tmp_dir: str, params: dict[str, object] | None = None) -> DatasetAnalysisContext:
    return DatasetAnalysisContext(
        out_dir=Path(tmp_dir),
        grains={
            "interface": pd.DataFrame(),
            "role": pd.DataFrame(
                [
                    {
                        "role": "vh",
                        "abseq__numbering_scheme": "imgt",
                        "abseq__cdr_definition": "imgt",
                        "abseq__cdr1_sequence": "GFTFSSYA",
                        "abseq__cdr2_sequence": "ISSGGGNT",
                        "abseq__cdr3_sequence": "ARDRGGYFDY",
                        "rolseq__sequence": VH_SEQ_A,
                    },
                    {
                        "role": "vh",
                        "abseq__numbering_scheme": "imgt",
                        "abseq__cdr_definition": "imgt",
                        "abseq__cdr1_sequence": "GFTFSSYA",
                        "abseq__cdr2_sequence": "ISSGGSNT",
                        "abseq__cdr3_sequence": "ARDRGGYFDY",
                        "rolseq__sequence": VH_SEQ_B,
                    },
                    {
                        "role": "vl",
                        "abseq__numbering_scheme": "imgt",
                        "abseq__cdr_definition": "imgt",
                        "abseq__cdr1_sequence": "QSISSS",
                        "abseq__cdr2_sequence": "DAS",
                        "abseq__cdr3_sequence": "QQYNSYPWT",
                        "rolseq__sequence": VL_SEQ_A,
                    },
                ]
            ),
        },
        params=params or {},
        annotations={},
    )


class CDREntropyTests(unittest.TestCase):
    def test_default_runs_all_cdrs_for_all_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = CDREntropyPlugin()
            out = plugin.run(_ctx(tmp_dir))

            self.assertEqual(sorted(out["role"].unique().tolist()), ["vh", "vl"])
            self.assertEqual(sorted(out["region"].unique().tolist()), ["cdr1", "cdr2", "cdr3"])
            self.assertEqual(out["row_kind"].dropna().unique().tolist(), ["position"])
            self.assertTrue(out["position"].astype(str).ne("").all())

    def test_can_select_single_role_and_single_cdr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = CDREntropyPlugin()
            out = plugin.run(
                _ctx(
                    tmp_dir,
                    params={
                        "roles": ["vh"],
                        "regions": ["cdr2"],
                    },
                )
            )

            self.assertEqual(out["role"].unique().tolist(), ["vh"])
            self.assertEqual(out["region"].unique().tolist(), ["cdr2"])
            self.assertEqual(out["position"].tolist(), ["H56", "H57", "H58", "H59", "H62", "H63", "H64", "H65"])
            self.assertEqual(out["source_column"].unique().tolist(), ["abseq__cdr2_sequence"])
            changed = out[out["position"] == "H63"].iloc[0]
            self.assertAlmostEqual(float(changed["shannon_entropy"]), 1.0)
            self.assertEqual(int(changed["n_sequences_total"]), 2)
            self.assertEqual(int(changed["n_observations"]), 2)
            self.assertEqual(int(changed["n_unique"]), 2)

    def test_can_select_full_sequence_entropy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = CDREntropyPlugin()
            out = plugin.run(
                _ctx(
                    tmp_dir,
                    params={
                        "roles": ["vh"],
                        "regions": ["sequence"],
                    },
                )
            )

            self.assertEqual(len(out), 1)
            self.assertEqual(out.iloc[0]["region"], "sequence")
            self.assertEqual(out.iloc[0]["row_kind"], "summary")
            self.assertEqual(out.iloc[0]["position"], "")
            self.assertEqual(out.iloc[0]["source_column"], "rolseq__sequence")
            self.assertEqual(int(out.iloc[0]["n_sequences_total"]), 2)
            self.assertEqual(int(out.iloc[0]["n_observations"]), 2)
            self.assertEqual(int(out.iloc[0]["n_unique"]), 2)
            self.assertAlmostEqual(float(out.iloc[0]["shannon_entropy"]), 1.0)


if __name__ == "__main__":
    unittest.main()
