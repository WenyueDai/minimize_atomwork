from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import minimum_atw.plugins.dataset.calculation.runtime as runtime_module
from minimum_atw.plugins.dataset.calculation.runtime import analyze_dataset_outputs
from minimum_atw.plugins.dataset.calculation.base import BaseDatasetPlugin
from minimum_atw.tests.helpers import read_dataset_analysis


VH_SEQ_A = "EVQLVESGGGLVQPGGSLRLSCAASGFTFSSYAMSWVRQAPGKGLEWVSAISSGGGNTYYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCARDRGGYFDYWGQGTLVTVSS"
VH_SEQ_B = "EVQLVESGGGLVQPGGSLRLSCAASGFTFSSYAMSWVRQAPGKGLEWVSAISSGGSNTYYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCARDRGGYFDYWGQGTLVTVSS"
VL_SEQ_A = "DIQMTQSPSSLSASVGDRVTITCRASQSISSSLAWYQQKPGKAPKLLIYDASSLESGVPSRFSGSGSGTDFTLTISSLQPEDFATYYCQQYNSYPWTFGQGTKVEIK"


def _write_test_pdb(
    out_dir: Path,
    *,
    interface_rows: list[dict] | None = None,
    role_rows: list[dict] | None = None,
) -> None:
    frames = []
    for row in (interface_rows or []):
        frames.append({**row, "grain": "interface"})
    for row in (role_rows or []):
        frames.append({**row, "grain": "role"})
    pd.DataFrame(frames).to_parquet(out_dir / "pdb.parquet", index=False)


class TestOverlapInterfaceSummaryPlugin(BaseDatasetPlugin):
    name = "test_overlap_interface_summary"

    def required_columns(self, _params: dict[str, object]) -> dict[str, list[str]]:
        return {
            "interface": ["path", "pair"],
            "role": ["path", "role"],
        }

    def run(self, ctx):
        return pd.DataFrame(
            [
                {
                    "analysis": self.name,
                    "n_interfaces_seen": int(len(ctx.df_interfaces)),
                    "n_roles_seen": int(len(ctx.df_roles)),
                }
            ]
        )


class TestOverlapInterfaceRolePlugin(BaseDatasetPlugin):
    name = "test_overlap_interface_role"

    def required_columns(self, _params: dict[str, object]) -> dict[str, list[str]]:
        return {
            "interface": ["path", "pair", "role_left"],
            "role": ["path", "role"],
        }

    def run(self, ctx):
        return pd.DataFrame(
            [
                {
                    "analysis": self.name,
                    "n_interfaces_seen": int(len(ctx.df_interfaces)),
                    "n_roles_seen": int(len(ctx.df_roles)),
                }
            ]
        )


class DatasetAnalysisRuntimeTests(unittest.TestCase):
    def test_runtime_passes_params_to_each_analysis_directly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_dataset_analysis_") as tmp_dir:
            out_dir = Path(tmp_dir)
            _write_test_pdb(
                out_dir,
                interface_rows=[
                    {"path": "/tmp/example_1.pdb", "assembly_id": "1", "pair": "vh__antigen", "role_left": "vh", "role_right": "antigen"},
                ],
                role_rows=[
                    {"path": "/tmp/example_1.pdb", "assembly_id": "1", "role": "vh", "abseq__numbering_scheme": "imgt", "abseq__cdr_definition": "imgt", "abseq__cdr1_sequence": "GFTFSSYA", "abseq__cdr2_sequence": "ISSGGGNT", "abseq__cdr3_sequence": "ARDRGGYFDY", "rolseq__sequence": VH_SEQ_A},
                    {"path": "/tmp/example_2.pdb", "assembly_id": "1", "role": "vh", "abseq__numbering_scheme": "imgt", "abseq__cdr_definition": "imgt", "abseq__cdr1_sequence": "GFTFSSYA", "abseq__cdr2_sequence": "ISSGGSNT", "abseq__cdr3_sequence": "ARDRGGYFDY", "rolseq__sequence": VH_SEQ_B},
                    {"path": "/tmp/example_3.pdb", "assembly_id": "1", "role": "vl", "abseq__numbering_scheme": "imgt", "abseq__cdr_definition": "imgt", "abseq__cdr1_sequence": "QSISSS", "abseq__cdr2_sequence": "DAS", "abseq__cdr3_sequence": "QQYNSYPWT", "rolseq__sequence": VL_SEQ_A},
                ],
            )

            summary = analyze_dataset_outputs(
                out_dir,
                dataset_analyses=("cdr_entropy",),
                dataset_analysis_params={
                    "cdr_entropy": {
                        "roles": ["vh"],
                        "regions": ["cdr2"],
                    }
                },
            )

            result = read_dataset_analysis(out_dir, "cdr_entropy")

            self.assertEqual(summary["dataset_analyses"], "cdr_entropy")
            self.assertEqual(len(result), 8)
            self.assertEqual(result["role"].unique().tolist(), ["vh"])
            self.assertEqual(result["region"].unique().tolist(), ["cdr2"])
            self.assertEqual(result["row_kind"].unique().tolist(), ["position"])
            changed = result[result["position"] == "H63"].iloc[0]
            self.assertAlmostEqual(float(changed["shannon_entropy"]), 1.0)

    def test_runtime_can_project_missing_interface_metric_columns(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_dataset_analysis_") as tmp_dir:
            out_dir = Path(tmp_dir)
            _write_test_pdb(
                out_dir,
                interface_rows=[
                    {"path": "/tmp/example_1.pdb", "assembly_id": "1", "pair": "vh__antigen", "role_left": "vh", "role_right": "antigen"},
                ],
            )

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

            _write_test_pdb(
                out_dir,
                interface_rows=[
                    {"path": "/tmp/example_1.pdb", "assembly_id": "1", "pair": "vh__antigen", "role_left": "vh", "role_right": "antigen"},
                ],
                role_rows=[
                    {"path": "/tmp/example_1.pdb", "assembly_id": "1", "role": "vh", "abseq__numbering_scheme": "imgt", "abseq__cdr_definition": "imgt", "abseq__cdr1_sequence": "GFTFSSYA", "abseq__cdr2_sequence": "ISSGGGNT", "abseq__cdr3_sequence": "ARDRGGYFDY", "rolseq__sequence": VH_SEQ_A},
                ],
            )
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
            _write_test_pdb(
                out_dir,
                interface_rows=[
                    {"path": "/tmp/example_1.pdb", "assembly_id": "1", "pair": "vh__antigen", "role_left": "vh", "role_right": "antigen"},
                ],
                role_rows=[
                    {"path": "/tmp/example_1.pdb", "assembly_id": "1", "role": "vh"},
                ],
            )

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

            _write_test_pdb(
                out_dir,
                interface_rows=[
                    {"path": "/tmp/example_1.pdb", "assembly_id": "1", "pair": "vh__antigen", "role_left": "vh", "role_right": "antigen"},
                ],
            )

            summary = analyze_dataset_outputs(
                out_dir,
                dataset_analyses=("interface_summary",),
                cleanup_prepared_after_dataset_analysis=True,
            )

            result = read_dataset_analysis(out_dir, "interface_summary")
            self.assertEqual(len(result), 1)
            self.assertEqual(summary["cleaned_prepared_outputs"], 1)
            self.assertFalse(prepared_dir.exists())

    def test_runtime_reuses_grain_reads_for_overlapping_analysis_requirements(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_dataset_analysis_") as tmp_dir:
            out_dir = Path(tmp_dir)
            _write_test_pdb(
                out_dir,
                interface_rows=[
                    {"path": "/tmp/example_1.pdb", "assembly_id": "1", "pair": "vh__antigen", "role_left": "vh", "role_right": "antigen"},
                ],
                role_rows=[
                    {"path": "/tmp/example_1.pdb", "assembly_id": "1", "role": "vh"},
                ],
            )

            read_calls: list[tuple[str, tuple[str, ...] | None]] = []
            real_read_output_table = runtime_module._read_output_table

            def counting_read_output_table(*args, **kwargs):
                grain = str(args[1])
                columns = kwargs.get("columns")
                read_calls.append((grain, tuple(columns) if columns is not None else None))
                return real_read_output_table(*args, **kwargs)

            with (
                mock.patch.dict(
                    runtime_module.DATASET_CALCULATION_REGISTRY,
                    {
                        "test_overlap_interface_summary": TestOverlapInterfaceSummaryPlugin(),
                        "test_overlap_interface_role": TestOverlapInterfaceRolePlugin(),
                    },
                    clear=False,
                ),
                mock.patch.object(runtime_module, "_read_output_table", side_effect=counting_read_output_table),
            ):
                summary = analyze_dataset_outputs(
                    out_dir,
                    dataset_analyses=("test_overlap_interface_summary", "test_overlap_interface_role"),
                )

            result = pd.read_parquet(out_dir / "dataset.parquet")

            self.assertEqual(summary["n_dataset_rows"], 2)
            self.assertEqual(sorted(result["analysis"].tolist()), ["test_overlap_interface_role", "test_overlap_interface_summary"])
            self.assertEqual(read_calls.count(("interface", ("path", "pair", "role_left"))), 1)
            self.assertEqual(read_calls.count(("role", ("path", "role"))), 1)
            self.assertEqual(len(read_calls), 2)


if __name__ == "__main__":
    unittest.main()
