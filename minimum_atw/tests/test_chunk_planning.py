from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    import yaml
    from minimum_atw.core.config import Config
    from minimum_atw.core.pipeline import merge_planned_chunks, plan_chunked_pipeline, run_pipeline
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "pydantic", "yaml", "pandas", "pyarrow"}:
        raise
    yaml = None
    Config = None
    merge_planned_chunks = None
    plan_chunked_pipeline = None
    run_pipeline = None


def _toy_complex_text() -> str:
    return textwrap.dedent(
        """\
        ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
        ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
        ATOM      3  N   GLY B   1       0.000   0.000   3.000  1.00 20.00           N
        ATOM      4  CA  GLY B   1       1.200   0.000   3.000  1.00 20.00           C
        TER
        END
        """
    )


@unittest.skipIf(run_pipeline is None, "pipeline dependencies are not installed")
class ChunkPlanningTests(unittest.TestCase):
    def test_plan_chunked_pipeline_creates_scheduler_ready_chunk_configs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_chunk_plan_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            input_dir.mkdir()
            for idx in range(3):
                (input_dir / f"toy_{idx + 1}.pdb").write_text(_toy_complex_text())

            cfg = yaml.safe_load(
                yaml.safe_dump(
                    {
                        "input_dir": str(input_dir),
                        "out_dir": str(root / "final_out"),
                        "roles": {"binder": ["A"], "target": ["B"]},
                        "interface_pairs": [["binder", "target"]],
                        "plugins": ["identity"],
                        "dataset_analyses": ["interface_summary"],
                    },
                    sort_keys=False,
                )
            )

            counts = plan_chunked_pipeline(Config(**cfg), chunk_size=2, plan_dir=root / "plan")

            self.assertEqual(counts["chunks"], 2)
            self.assertEqual(counts["planned_structures"], 3)

            plan = json.loads((root / "plan" / "chunk_plan.json").read_text())
            self.assertEqual(plan["output_kind"], "chunk_plan")
            self.assertEqual(len(plan["chunks"]), 2)
            first_chunk = plan["chunks"][0]
            chunk_cfg = yaml.safe_load(Path(first_chunk["chunk_config_path"]).read_text())

            self.assertEqual(chunk_cfg["dataset_analyses"], [])
            self.assertFalse(chunk_cfg["keep_intermediate_outputs"])
            self.assertEqual(first_chunk["n_input_files"], 2)
            self.assertTrue(Path(first_chunk["chunk_input_dir"]).exists())

    def test_merge_planned_chunks_runs_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_chunk_plan_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            input_dir.mkdir()
            for idx in range(3):
                (input_dir / f"toy_{idx + 1}.pdb").write_text(_toy_complex_text())

            cfg = Config(
                input_dir=str(input_dir),
                out_dir=str(root / "merged_out"),
                roles={"binder": ["A"], "target": ["B"]},
                interface_pairs=[("binder", "target")],
                plugins=["identity"],
                dataset_analyses=["interface_summary"],
            )

            plan_chunked_pipeline(cfg, chunk_size=2, plan_dir=root / "plan")
            plan = json.loads((root / "plan" / "chunk_plan.json").read_text())

            for chunk in plan["chunks"]:
                chunk_cfg = Config(**yaml.safe_load(Path(chunk["chunk_config_path"]).read_text()))
                run_pipeline(chunk_cfg)

            counts = merge_planned_chunks(root / "plan")

            self.assertEqual(counts["structures"], 3)
            self.assertEqual(counts["chunks"], 2)
            self.assertTrue((root / "merged_out" / "dataset_metadata.json").exists())
            self.assertTrue((root / "merged_out" / "dataset_analysis" / "interface_summary.parquet").exists())


if __name__ == "__main__":
    unittest.main()
