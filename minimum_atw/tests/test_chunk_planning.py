from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

try:
    import yaml
    import minimum_atw.runtime.chunked as chunked_module
    from minimum_atw.core.config import Config
    from minimum_atw.core.pipeline import merge_planned_chunks, plan_chunked_pipeline, run_chunked_pipeline, run_pipeline
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "pydantic", "yaml", "pandas", "pyarrow"}:
        raise
    yaml = None
    Config = None
    chunked_module = None
    merge_planned_chunks = None
    plan_chunked_pipeline = None
    run_chunked_pipeline = None
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


class _PermissionErrorProcessPool:
    def __init__(self, *args, **kwargs):
        raise PermissionError("process pools are unavailable in this test")


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
            self.assertEqual(plan["resource_plan"]["cpu_workers_per_chunk"], 1)
            self.assertEqual(plan["resource_plan"]["cpu_threads_per_chunk"], 1)
            self.assertEqual(plan["resource_plan"]["gpu_workers_per_chunk"], 0)
            self.assertEqual(plan["resource_plan"]["gpu_devices_per_chunk"], 0)
            self.assertEqual(plan["resource_plan"]["max_concurrent_chunks"], 2)
            first_chunk = plan["chunks"][0]
            chunk_cfg = yaml.safe_load(Path(first_chunk["chunk_config_path"]).read_text())

            self.assertEqual(chunk_cfg["dataset_analyses"], [])
            self.assertFalse(chunk_cfg["keep_intermediate_outputs"])
            self.assertEqual(first_chunk["n_input_files"], 2)
            self.assertTrue(Path(first_chunk["chunk_input_dir"]).exists())

    def test_plan_chunked_pipeline_can_keep_dataset_analyses_per_chunk(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_chunk_plan_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            input_dir.mkdir()
            for idx in range(3):
                (input_dir / f"toy_{idx + 1}.pdb").write_text(_toy_complex_text())

            cfg = Config(
                input_dir=str(input_dir),
                out_dir=str(root / "final_out"),
                roles={"binder": ["A"], "target": ["B"]},
                interface_pairs=[("binder", "target")],
                plugins=["identity"],
                dataset_analyses=["interface_summary"],
                dataset_analysis_mode="per_chunk",
            )

            plan_chunked_pipeline(cfg, chunk_size=2, plan_dir=root / "plan")
            plan = json.loads((root / "plan" / "chunk_plan.json").read_text())
            first_chunk = plan["chunks"][0]
            chunk_cfg = yaml.safe_load(Path(first_chunk["chunk_config_path"]).read_text())

            self.assertEqual(chunk_cfg["dataset_analyses"], ["interface_summary"])
            self.assertEqual(chunk_cfg["dataset_analysis_mode"], "per_chunk")

    def test_plan_chunked_pipeline_records_resource_plan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_chunk_plan_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            input_dir.mkdir()
            for idx in range(4):
                (input_dir / f"toy_{idx + 1}.pdb").write_text(_toy_complex_text())

            cfg = Config(
                input_dir=str(input_dir),
                out_dir=str(root / "final_out"),
                roles={"binder": ["A"], "target": ["B"]},
                interface_pairs=[("binder", "target")],
                plugins=["identity"],
                cpu_workers=4,
                chunk_cpu_capacity=8,
            )

            plan_chunked_pipeline(cfg, chunk_size=1, plan_dir=root / "plan")
            plan = json.loads((root / "plan" / "chunk_plan.json").read_text())
            resource_plan = dict(plan["resource_plan"])

            self.assertEqual(resource_plan["cpu_capacity"], 8)
            self.assertEqual(resource_plan["cpu_workers_per_chunk"], 4)
            self.assertEqual(resource_plan["gpu_workers_per_chunk"], 0)
            self.assertEqual(resource_plan["max_concurrent_chunks"], 2)
            self.assertEqual(resource_plan["gpu_devices"], [])
            self.assertEqual(resource_plan["recommended_chunk_job"], {"cpu_threads": 4, "gpu_devices": 0})
            self.assertEqual(resource_plan["submission_plan"]["recommended_mode"], "cpu_only")
            self.assertEqual(
                resource_plan["submission_plan"]["single_chunk_job"],
                {"cpu_threads": 4, "gpu_devices": 0},
            )
            self.assertEqual(resource_plan["scheduling_errors"], [])
            self.assertEqual(
                resource_plan["waves"],
                [{"wave": 0, "cpu_workers": 4, "gpu_workers": 0, "group_ids": [0]}],
            )

    def test_plan_chunked_pipeline_records_unschedulable_local_resource_plan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_chunk_plan_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            input_dir.mkdir()
            for idx in range(2):
                (input_dir / f"toy_{idx + 1}.pdb").write_text(_toy_complex_text())

            cfg = Config(
                input_dir=str(input_dir),
                out_dir=str(root / "final_out"),
                roles={"binder": ["A"], "target": ["B"]},
                interface_pairs=[("binder", "target")],
                plugins=["identity"],
                cpu_workers=8,
            )

            with mock.patch("minimum_atw.runtime.chunked._cpu_capacity", return_value=4):
                plan_chunked_pipeline(cfg, chunk_size=1, plan_dir=root / "plan")

            plan = json.loads((root / "plan" / "chunk_plan.json").read_text())
            resource_plan = dict(plan["resource_plan"])

            self.assertEqual(resource_plan["cpu_capacity"], 4)
            self.assertEqual(resource_plan["cpu_workers_per_chunk"], 8)
            self.assertEqual(resource_plan["cpu_threads_per_chunk"], 8)
            self.assertEqual(resource_plan["max_concurrent_chunks"], 0)
            self.assertEqual(
                resource_plan["scheduling_errors"],
                ["Chunk scheduling requires 8 CPU workers per chunk but only 4 are available on this node"],
            )

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
            self.assertTrue((root / "merged_out" / "dataset.parquet").exists())

    def test_merge_planned_chunks_skips_post_merge_dataset_analysis_in_per_chunk_mode(self) -> None:
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
                dataset_analysis_mode="per_chunk",
            )

            plan_chunked_pipeline(cfg, chunk_size=2, plan_dir=root / "plan")
            plan = json.loads((root / "plan" / "chunk_plan.json").read_text())

            for chunk in plan["chunks"]:
                chunk_cfg = Config(**yaml.safe_load(Path(chunk["chunk_config_path"]).read_text()))
                run_pipeline(chunk_cfg)
                self.assertTrue((Path(chunk["chunk_out_dir"]) / "dataset.parquet").exists())

            counts = merge_planned_chunks(root / "plan")

            self.assertEqual(counts["structures"], 3)
            self.assertFalse((root / "merged_out" / "dataset.parquet").exists())

    def test_run_chunked_pipeline_limits_effective_workers_by_chunk_cpu_capacity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_chunk_plan_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            input_dir.mkdir()
            for idx in range(4):
                (input_dir / f"toy_{idx + 1}.pdb").write_text(_toy_complex_text())

            cfg = Config(
                input_dir=str(input_dir),
                out_dir=str(root / "merged_out"),
                roles={"binder": ["A"], "target": ["B"]},
                interface_pairs=[("binder", "target")],
                plugins=["identity"],
                cpu_workers=4,
                chunk_cpu_capacity=8,
            )

            seen_jobs: list[int] = []

            def fake_run_chunk_job(**job):
                seen_jobs.append(int(job["chunk_index"]))
                chunk_out_dir = Path(job["workspace_dir"]) / chunked_module.chunk_dir_name(int(job["chunk_index"])) / "out"
                chunk_out_dir.mkdir(parents=True, exist_ok=True)
                return {
                    "chunk_index": int(job["chunk_index"]),
                    "chunk_input_dir": str(Path(job["workspace_dir"]) / "input"),
                    "chunk_out_dir": str(chunk_out_dir),
                    "n_input_files": len(job["chunk_paths"]),
                    "counts": {"structures": len(job["chunk_paths"])},
                    "assigned_gpu_devices": [],
                }

            with (
                mock.patch("minimum_atw.runtime.chunked.concurrent.futures.ProcessPoolExecutor", _PermissionErrorProcessPool),
                mock.patch("minimum_atw.runtime.chunked._run_chunk_job", side_effect=fake_run_chunk_job),
                mock.patch("minimum_atw.core.pipeline.merge_dataset_outputs", return_value={"structures": 4}),
            ):
                counts = run_chunked_pipeline(cfg, chunk_size=1, workers=10)

            self.assertEqual(sorted(seen_jobs), [1, 2, 3, 4])
            self.assertEqual(counts["workers_requested"], 10)
            self.assertEqual(counts["workers"], 2)
            self.assertEqual(counts["cpu_capacity"], 8)
            self.assertEqual(counts["cpu_workers_per_chunk"], 4)

    def test_chunk_worker_plan_sums_same_wave_pool_budgets(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            roles={"binder": ["A"], "target": ["B"]},
            interface_pairs=[("binder", "target")],
            plugins=["identity"],
            chunk_cpu_capacity=10,
        )

        fake_metadata = {
            "groups": [
                {"group_id": 0, "wave": 0, "worker_pool": "cpu", "planned_workers": 2},
                {"group_id": 1, "wave": 0, "worker_pool": "cpu", "planned_workers": 3},
                {"group_id": 2, "wave": 1, "worker_pool": "gpu", "planned_workers": 1},
            ]
        }

        with mock.patch("minimum_atw.runtime.chunked.plugin_execution_metadata", return_value=fake_metadata):
            plan = chunked_module._chunk_worker_plan(cfg, requested_workers=10, n_chunks=10)

        self.assertEqual(plan.cpu_workers_per_chunk, 5)
        self.assertEqual(plan.gpu_workers_per_chunk, 1)
        self.assertEqual(
            plan.resource_waves,
            (
                chunked_module.ChunkWaveResources(wave=0, cpu_workers=5, gpu_workers=0, group_ids=(0, 1)),
                chunked_module.ChunkWaveResources(wave=1, cpu_workers=1, gpu_workers=1, group_ids=(2,)),
            ),
        )
        self.assertEqual(plan.submission_plan["recommended_mode"], "single_job")
        self.assertEqual(plan.scheduling_errors, ())

    def test_chunk_worker_plan_exposes_split_stage_submission_manifest(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            roles={"binder": ["A"], "target": ["B"]},
            interface_pairs=[("binder", "target")],
            plugins=["identity"],
            chunk_cpu_capacity=8,
        )

        fake_metadata = {
            "groups": [
                {"group_id": 0, "wave": 0, "worker_pool": "cpu", "planned_cpu_threads": 4, "planned_gpu_devices": 0},
                {"group_id": 1, "wave": 1, "worker_pool": "gpu", "planned_cpu_threads": 1, "planned_gpu_devices": 1},
            ],
            "scheduler_resources": {
                "single_job": {"cpu_threads": 4, "gpu_devices": 1},
                "submission_plan": {
                    "recommended_mode": "split_by_stage",
                    "reason": "CPU-only and GPU-enabled waves are both present, so staged submission can release GPU nodes during CPU-only phases.",
                    "stages": [
                        {
                            "stage": 0,
                            "worker_pools": ["cpu"],
                            "cpu_threads": 4,
                            "gpu_devices": 0,
                            "jobs": [
                                {
                                    "job_id": "stage0-cpu",
                                    "worker_pool": "cpu",
                                    "resource_class": "cpu_only",
                                    "device_kind": "cpu",
                                    "cpu_threads": 4,
                                    "gpu_devices": 0,
                                    "group_ids": [0],
                                    "plugins": ["identity"],
                                }
                            ],
                        },
                        {
                            "stage": 1,
                            "worker_pools": ["gpu"],
                            "cpu_threads": 1,
                            "gpu_devices": 1,
                            "jobs": [
                                {
                                    "job_id": "stage1-gpu",
                                    "worker_pool": "gpu",
                                    "resource_class": "gpu_enabled",
                                    "device_kind": "cuda",
                                    "cpu_threads": 1,
                                    "gpu_devices": 1,
                                    "group_ids": [1],
                                    "plugins": ["esm_if1_score"],
                                }
                            ],
                        },
                    ],
                    "job_classes": [
                        {
                            "worker_pool": "cpu",
                            "resource_class": "cpu_only",
                            "device_kind": "cpu",
                            "peak_cpu_threads": 4,
                            "peak_gpu_devices": 0,
                            "stages": [0],
                        },
                        {
                            "worker_pool": "gpu",
                            "resource_class": "gpu_enabled",
                            "device_kind": "cuda",
                            "peak_cpu_threads": 1,
                            "peak_gpu_devices": 1,
                            "stages": [1],
                        },
                    ],
                },
            },
        }

        with mock.patch("minimum_atw.runtime.chunked.plugin_execution_metadata", return_value=fake_metadata):
            plan = chunked_module._chunk_worker_plan(cfg, requested_workers=10, n_chunks=10)

        self.assertEqual(plan.submission_plan["recommended_mode"], "split_by_stage")
        self.assertEqual(
            plan.submission_plan["single_chunk_job"],
            {"cpu_threads": 4, "gpu_devices": 1},
        )
        self.assertEqual(
            plan.submission_plan["job_classes"],
            [
                {
                    "worker_pool": "cpu",
                    "resource_class": "cpu_only",
                    "device_kind": "cpu",
                    "peak_cpu_threads": 4,
                    "peak_gpu_devices": 0,
                    "stages": [0],
                    "recommended_chunk_job": {"cpu_threads": 4, "gpu_devices": 0},
                },
                {
                    "worker_pool": "gpu",
                    "resource_class": "gpu_enabled",
                    "device_kind": "cuda",
                    "peak_cpu_threads": 1,
                    "peak_gpu_devices": 1,
                    "stages": [1],
                    "recommended_chunk_job": {"cpu_threads": 1, "gpu_devices": 1},
                },
            ],
        )

    def test_run_chunked_pipeline_assigns_disjoint_gpu_slot_devices(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_chunk_plan_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            input_dir.mkdir()
            for idx in range(4):
                (input_dir / f"toy_{idx + 1}.pdb").write_text(_toy_complex_text())

            cfg = Config(
                input_dir=str(input_dir),
                out_dir=str(root / "merged_out"),
                roles={"binder": ["A"], "target": ["B"]},
                interface_pairs=[("binder", "target")],
                plugins=["identity", "esm_if1_score"],
                gpu_workers=1,
                gpu_devices=["0", "1"],
                plugin_params={"esm_if1_score": {"device": "auto"}},
            )

            seen_assigned_devices: list[tuple[str, ...]] = []

            def fake_run_chunk_job(**job):
                assigned_gpu_devices = tuple(str(item) for item in job.get("assigned_gpu_devices") or [])
                seen_assigned_devices.append(assigned_gpu_devices)
                chunk_out_dir = Path(job["workspace_dir"]) / chunked_module.chunk_dir_name(int(job["chunk_index"])) / "out"
                chunk_out_dir.mkdir(parents=True, exist_ok=True)
                return {
                    "chunk_index": int(job["chunk_index"]),
                    "chunk_input_dir": str(Path(job["workspace_dir"]) / "input"),
                    "chunk_out_dir": str(chunk_out_dir),
                    "n_input_files": len(job["chunk_paths"]),
                    "counts": {"structures": len(job["chunk_paths"])},
                    "assigned_gpu_devices": list(assigned_gpu_devices),
                }

            with (
                mock.patch("minimum_atw.runtime.chunked.concurrent.futures.ProcessPoolExecutor", _PermissionErrorProcessPool),
                mock.patch("minimum_atw.runtime.chunked._run_chunk_job", side_effect=fake_run_chunk_job),
                mock.patch("minimum_atw.core.pipeline.merge_dataset_outputs", return_value={"structures": 4}),
            ):
                counts = run_chunked_pipeline(cfg, chunk_size=1, workers=10)

            self.assertEqual(counts["workers"], 2)
            self.assertEqual(counts["gpu_workers_per_chunk"], 1)
            self.assertEqual(set(seen_assigned_devices), {("0",), ("1",)})


if __name__ == "__main__":
    unittest.main()
