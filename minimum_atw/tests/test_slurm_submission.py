from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import yaml
    import minimum_atw.runtime.slurm as slurm_module
    from minimum_atw.core.config import Config
except ModuleNotFoundError as exc:
    if exc.name not in {"pydantic", "yaml", "pandas", "pyarrow"}:
        raise
    yaml = None
    slurm_module = None
    Config = None


def _base_config(root: Path, *, dataset_analysis_mode: str = "post_merge") -> Config:
    (root / "input").mkdir(parents=True, exist_ok=True)
    return Config(
        input_dir=str(root / "input"),
        out_dir=str(root / "final_out"),
        roles={"binder": ["A"], "target": ["B"]},
        interface_pairs=[("binder", "target")],
        plugins=["identity"],
        dataset_analyses=["interface_summary"],
        dataset_analysis_mode=dataset_analysis_mode,
    )


def _write_plan(
    plan_dir: Path,
    *,
    source_cfg: Config,
    resource_plan: dict[str, object],
    n_chunks: int = 2,
) -> dict[str, object]:
    plan_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[dict[str, object]] = []
    for idx in range(1, n_chunks + 1):
        chunk_dir = plan_dir / f"chunk_{idx:03d}"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_input_dir = chunk_dir / "input"
        chunk_out_dir = chunk_dir / "out"
        chunk_input_dir.mkdir(exist_ok=True)
        chunk_out_dir.mkdir(exist_ok=True)
        chunk_config_path = chunk_dir / "config.yaml"
        chunk_cfg = source_cfg.chunk_config(input_dir=chunk_input_dir, out_dir=chunk_out_dir).model_dump(mode="json")
        chunk_config_path.write_text(yaml.safe_dump(chunk_cfg, sort_keys=False))
        chunks.append(
            {
                "chunk_index": idx,
                "chunk_dir": str(chunk_dir.resolve()),
                "chunk_input_dir": str(chunk_input_dir.resolve()),
                "chunk_out_dir": str(chunk_out_dir.resolve()),
                "chunk_config_path": str(chunk_config_path.resolve()),
                "n_input_files": 1,
                "input_files": [str((chunk_input_dir / f"toy_{idx}.pdb").resolve())],
            }
        )

    plan = {
        "output_kind": "chunk_plan",
        "source_config": source_cfg.model_dump(mode="json"),
        "chunk_size": 10,
        "planned_structures": n_chunks,
        "resource_plan": resource_plan,
        "chunks": chunks,
    }
    (plan_dir / slurm_module.CHUNK_PLAN_NAME).write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    return plan


@unittest.skipIf(slurm_module is None, "slurm submission dependencies are not installed")
class SlurmSubmissionTests(unittest.TestCase):
    def test_submit_slurm_plan_auto_uses_mixed_mode_for_single_job_plan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_slurm_") as tmp_dir:
            root = Path(tmp_dir)
            source_cfg = _base_config(root)
            plan_dir = root / "plan"
            _write_plan(
                plan_dir,
                source_cfg=source_cfg,
                resource_plan={
                    "recommended_chunk_job": {"cpu_threads": 4, "gpu_devices": 1},
                    "submission_plan": {
                        "recommended_mode": "single_job",
                        "reason": "Mixed submission is simplest for this plan.",
                    },
                },
            )

            submission = slurm_module.submit_slurm_plan(
                plan_dir,
                workdir=root,
                python_bin=sys.executable,
                dry_run=True,
            )

            self.assertEqual(submission["mode_submitted"], "mixed")
            self.assertEqual(
                [job["label"] for job in submission["jobs"]],
                ["mixed_chunks", "merge_planned_chunks"],
            )
            self.assertTrue((plan_dir / slurm_module.SLURM_SUBMISSION_NAME).exists())
            manifest_lines = (plan_dir / slurm_module.SLURM_MANIFEST_NAME).read_text().strip().splitlines()
            self.assertEqual(len(manifest_lines), 2)
            self.assertTrue(all(line.endswith("config.yaml") for line in manifest_lines))

            mixed_script = (plan_dir / slurm_module.SLURM_SCRIPT_DIRNAME / "10_mixed_chunks.sh").read_text()
            self.assertIn('-m minimum_atw.cli run --config "$CONFIG"', mixed_script)

            merge_script = (plan_dir / slurm_module.SLURM_SCRIPT_DIRNAME / "99_merge_planned_chunks.sh").read_text()
            self.assertIn("-m minimum_atw.cli merge-planned-chunks", merge_script)
            self.assertIn(str(plan_dir.resolve()), merge_script)

    def test_submit_slurm_plan_staged_creates_prepare_stage_merge_and_analyze_jobs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_slurm_") as tmp_dir:
            root = Path(tmp_dir)
            source_cfg = _base_config(root, dataset_analysis_mode="per_chunk")
            plan_dir = root / "plan"
            _write_plan(
                plan_dir,
                source_cfg=source_cfg,
                resource_plan={
                    "recommended_chunk_job": {"cpu_threads": 4, "gpu_devices": 1},
                    "submission_plan": {
                        "recommended_mode": "split_by_stage",
                        "reason": "Split CPU and GPU stages to release GPU nodes during CPU-only work.",
                        "stages": [
                            {
                                "stage": 0,
                                "jobs": [
                                    {
                                        "job_id": "stage0-cpu",
                                        "worker_pool": "cpu",
                                        "plugins": ["identity", "interface_metrics"],
                                        "recommended_chunk_job": {"cpu_threads": 4, "gpu_devices": 0},
                                    },
                                    {
                                        "job_id": "stage0-gpu",
                                        "worker_pool": "gpu",
                                        "plugins": ["abepitope_score"],
                                        "recommended_chunk_job": {"cpu_threads": 2, "gpu_devices": 1},
                                    },
                                ],
                            },
                            {
                                "stage": 1,
                                "jobs": [
                                    {
                                        "job_id": "stage1-cpu",
                                        "worker_pool": "cpu",
                                        "plugins": ["pdockq_score"],
                                        "recommended_chunk_job": {"cpu_threads": 4, "gpu_devices": 0},
                                    }
                                ],
                            },
                        ],
                    },
                },
            )

            submission = slurm_module.submit_slurm_plan(
                plan_dir,
                workdir=root,
                python_bin=sys.executable,
                dry_run=True,
            )

            self.assertEqual(submission["mode_submitted"], "staged")
            self.assertEqual(
                [job["label"] for job in submission["jobs"]],
                [
                    "prepare_chunks",
                    "stage0_cpu",
                    "stage0_gpu",
                    "stage1_cpu",
                    "merge_chunks",
                    "analyze_chunks",
                    "merge_planned_chunks",
                ],
            )

            jobs_by_label = {job["label"]: job for job in submission["jobs"]}
            self.assertEqual(jobs_by_label["stage0_cpu"]["depends_on_labels"], ["prepare_chunks"])
            self.assertEqual(jobs_by_label["stage0_gpu"]["depends_on_labels"], ["prepare_chunks"])
            self.assertEqual(jobs_by_label["stage1_cpu"]["depends_on_labels"], ["stage0_cpu", "stage0_gpu"])
            self.assertEqual(jobs_by_label["merge_chunks"]["depends_on_labels"], ["stage1_cpu"])
            self.assertEqual(jobs_by_label["analyze_chunks"]["depends_on_labels"], ["merge_chunks"])
            self.assertEqual(jobs_by_label["merge_planned_chunks"]["depends_on_labels"], ["analyze_chunks"])

            stage0_cpu_script = (plan_dir / slurm_module.SLURM_SCRIPT_DIRNAME / "10_stage0_cpu.sh").read_text()
            self.assertIn("--plugins identity interface_metrics", stage0_cpu_script)
            stage0_gpu_script = (plan_dir / slurm_module.SLURM_SCRIPT_DIRNAME / "10_stage0_gpu.sh").read_text()
            self.assertIn("--plugins abepitope_score", stage0_gpu_script)
            analyze_script = (plan_dir / slurm_module.SLURM_SCRIPT_DIRNAME / "95_analyze_chunks.sh").read_text()
            self.assertIn("-m minimum_atw.cli analyze-dataset", analyze_script)

    def test_submit_slurm_plan_calls_sbatch_with_dependencies(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_slurm_") as tmp_dir:
            root = Path(tmp_dir)
            source_cfg = _base_config(root, dataset_analysis_mode="per_chunk")
            plan_dir = root / "plan"
            _write_plan(
                plan_dir,
                source_cfg=source_cfg,
                resource_plan={
                    "recommended_chunk_job": {"cpu_threads": 4, "gpu_devices": 1},
                    "submission_plan": {
                        "recommended_mode": "split_by_stage",
                        "reason": "Split CPU and GPU stages to release GPU nodes during CPU-only work.",
                        "stages": [
                            {
                                "stage": 0,
                                "jobs": [
                                    {
                                        "job_id": "stage0-cpu",
                                        "worker_pool": "cpu",
                                        "plugins": ["identity"],
                                        "recommended_chunk_job": {"cpu_threads": 4, "gpu_devices": 0},
                                    },
                                    {
                                        "job_id": "stage0-gpu",
                                        "worker_pool": "gpu",
                                        "plugins": ["abepitope_score"],
                                        "recommended_chunk_job": {"cpu_threads": 2, "gpu_devices": 1},
                                    },
                                ],
                            },
                            {
                                "stage": 1,
                                "jobs": [
                                    {
                                        "job_id": "stage1-cpu",
                                        "worker_pool": "cpu",
                                        "plugins": ["pdockq_score"],
                                        "recommended_chunk_job": {"cpu_threads": 3, "gpu_devices": 0},
                                    }
                                ],
                            },
                        ],
                    },
                },
            )

            submitted_commands: list[list[str]] = []
            returned_job_ids = iter(["1000", "1001", "1002", "1003", "1004", "1005", "1006"])

            def _fake_run(cmd: list[str], **kwargs: object) -> mock.Mock:
                submitted_commands.append(list(cmd))
                return mock.Mock(stdout=next(returned_job_ids) + "\n")

            with mock.patch("minimum_atw.runtime.slurm.subprocess.run", side_effect=_fake_run):
                submission = slurm_module.submit_slurm_plan(
                    plan_dir,
                    workdir=root,
                    python_bin=sys.executable,
                    dry_run=False,
                    sbatch_common_args=["--account=proj"],
                    sbatch_cpu_args=["--partition=cpu"],
                    sbatch_gpu_args=["--partition=gpu"],
                    sbatch_merge_args=["--partition=bigmem"],
                )

            self.assertEqual(
                [job["job_id"] for job in submission["jobs"]],
                ["1000", "1001", "1002", "1003", "1004", "1005", "1006"],
            )
            self.assertIn("--partition=cpu", submitted_commands[0])
            self.assertIn("--dependency=afterok:1000", submitted_commands[1])
            self.assertIn("--dependency=afterok:1000", submitted_commands[2])
            self.assertIn("--partition=gpu", submitted_commands[2])
            self.assertIn("--gres=gpu:1", submitted_commands[2])
            self.assertIn("--dependency=afterok:1001:1002", submitted_commands[3])
            self.assertIn("--dependency=afterok:1003", submitted_commands[4])
            self.assertIn("--dependency=afterok:1004", submitted_commands[5])
            self.assertIn("--dependency=afterok:1005", submitted_commands[6])
            self.assertIn("--partition=bigmem", submitted_commands[6])


if __name__ == "__main__":
    unittest.main()
