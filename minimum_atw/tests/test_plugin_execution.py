from __future__ import annotations

import io
import json
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from unittest import mock

try:
    import pandas as pd
    from minimum_atw.core.config import Config
    from minimum_atw.core.pipeline import merge_outputs, prepare_outputs, run_plugins
    from minimum_atw.plugins.base import BasePlugin, InterfacePlugin
    from minimum_atw.plugins.pdb.calculation.interface_analysis.abepitope_score import AbEpiTopeScorePlugin
    from minimum_atw.tests.helpers import read_pdb_grain
    import minimum_atw.core._execute as execute_module
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "pydantic", "pandas", "pyarrow"}:
        raise
    pd = None
    Config = None
    read_pdb_grain = None


class _PermissionErrorProcessPool:
    def __init__(self, *args, **kwargs):
        raise PermissionError("process pools are unavailable in this test")


class _FakeAbEpiTopeProcess:
    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO('{"ok": true, "event": "ready"}\n')
        self.stderr = io.StringIO()
        self.returncode = None
        self.wait_calls: list[float | None] = []
        self.kill_called = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        self.returncode = 0
        return 0

    def kill(self):
        self.kill_called = True
        self.returncode = -9


class TestLightStructurePlugin(BasePlugin):
    name = "test_light_structure"
    prefix = "light_structure"
    input_model = "atom_array"
    execution_mode = "batched"
    failure_policy = "continue"

    def run(self, ctx):
        yield {
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "signal": 11,
        }


class TestLightInterfacePlugin(InterfacePlugin):
    name = "test_light_interface"
    prefix = "light_interface"
    input_model = "atom_array"
    execution_mode = "batched"
    failure_policy = "continue"

    def run(self, ctx):
        for left_role, right_role, left, right in self.iter_role_pairs(ctx):
            yield {
                **self.pair_identity_row(ctx, left_role=left_role, right_role=right_role),
                "label": f"{left_role}:{right_role}:{len(left)}:{len(right)}",
            }


class TestHeavyFailurePlugin(BasePlugin):
    name = "test_heavy_failure"
    prefix = "heavy_failure"
    input_model = "prepared_file"
    execution_mode = "isolated"
    failure_policy = "continue"

    def run(self, ctx):
        raise RuntimeError("heavy plugin failed")


class TestGpuStructurePlugin(BasePlugin):
    name = "test_gpu_structure"
    prefix = "gpu_structure"
    input_model = "atom_array"
    execution_mode = "batched"
    worker_pool = "gpu"
    device_kind = "cuda"
    failure_policy = "continue"

    def run(self, ctx):
        yield {
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "signal": 17,
            "device": str(self.plugin_params(ctx).get("device", "unset")),
        }


class TestDependentGpuPlugin(BasePlugin):
    name = "test_dependent_gpu"
    prefix = "dependent_gpu"
    input_model = "atom_array"
    execution_mode = "batched"
    worker_pool = "gpu"
    device_kind = "cuda"
    requires = ["test_light_structure"]
    failure_policy = "continue"

    def run(self, ctx):
        yield {
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "signal": 23,
        }


class TestWideCpuPlugin(BasePlugin):
    name = "test_wide_cpu"
    prefix = "wide_cpu"
    input_model = "atom_array"
    execution_mode = "batched"
    cpu_threads_per_worker = 2
    failure_policy = "continue"

    def run(self, ctx):
        yield {
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "signal": 29,
        }


@unittest.skipIf(Config is None, "pipeline dependencies are not installed")
class PluginExecutionModelTests(unittest.TestCase):
    def _write_complexes(self, input_dir: Path, *, count: int) -> None:
        for idx in range(count):
            (input_dir / f"toy_complex_{idx + 1}.pdb").write_text(
                textwrap.dedent(
                    f"""\
                    ATOM      1  N   GLY A   1       {idx:0.3f}   0.000   0.000  1.00 20.00           N
                    ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                    ATOM      3  N   GLY B   1       0.000   0.000   3.000  1.00 20.00           N
                    ATOM      4  CA  GLY B   1       1.200   0.000   3.000  1.00 20.00           C
                    TER
                    END
                    """
                )
            )

    def test_atom_array_plugins_batch_and_file_boundary_plugin_isolates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_execution_test_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            input_dir.mkdir()

            (input_dir / "toy_complex.pdb").write_text(
                textwrap.dedent(
                    """\
                    ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                    ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                    ATOM      3  N   GLY B   1       0.000   0.000   3.000  1.00 20.00           N
                    ATOM      4  CA  GLY B   1       1.200   0.000   3.000  1.00 20.00           C
                    TER
                    END
                    """
                )
            )

            cfg = Config(
                input_dir=str(input_dir),
                out_dir=str(out_dir),
                roles={"binder": ["A"], "target": ["B"]},
                interface_pairs=[("binder", "target")],
                plugins=[
                    "test_light_structure",
                    "test_light_interface",
                    "test_heavy_failure",
                ],
                keep_intermediate_outputs=True,
            )

            prepare_outputs(cfg)

            real_prepare_context = execute_module._prepare_context
            load_calls: list[str] = []

            def counting_prepare_context(source_path, prepared_path, runtime_cfg):
                load_calls.append(str(source_path))
                return real_prepare_context(source_path, prepared_path, runtime_cfg)

            with (
                mock.patch.dict(
                    execute_module.PLUGIN_REGISTRY,
                    {
                        "test_light_structure": TestLightStructurePlugin(),
                        "test_light_interface": TestLightInterfacePlugin(),
                        "test_heavy_failure": TestHeavyFailurePlugin(),
                    },
                    clear=True,
                ),
                mock.patch("minimum_atw.core._execute._prepare_context", side_effect=counting_prepare_context),
            ):
                plugin_counts = run_plugins(cfg, cfg.plugins)
                merged_counts = merge_outputs(cfg)

            self.assertEqual(len(load_calls), 1)
            self.assertEqual(plugin_counts["structures"], 1)
            self.assertEqual(plugin_counts["interfaces"], 1)
            self.assertEqual(plugin_counts["status"], 3)
            self.assertEqual(plugin_counts["bad"], 0)
            self.assertEqual(merged_counts["structures"], 1)
            self.assertEqual(merged_counts["interfaces"], 1)

            structures = read_pdb_grain(out_dir, "structure")
            interfaces = read_pdb_grain(out_dir, "interface")
            statuses = pd.read_parquet(out_dir / "plugin_status.parquet")
            metadata = json.loads((out_dir / "run_metadata.json").read_text())

            self.assertIn("light_structure__signal", structures.columns)
            self.assertEqual(structures.loc[0, "light_structure__signal"], 11)
            self.assertIn("light_interface__label", interfaces.columns)
            self.assertIn("binder:target", interfaces.loc[0, "light_interface__label"])

            status_map = {
                row.plugin: row.status
                for row in statuses.itertuples(index=False)
            }
            self.assertEqual(status_map["test_light_structure"], "ok")
            self.assertEqual(status_map["test_light_interface"], "ok")
            self.assertEqual(status_map["test_heavy_failure"], "failed")

            self.assertEqual(
                metadata["plugin_execution"]["groups"],
                [
                    {
                        "group_id": 0,
                        "depends_on_groups": [],
                        "wave": 0,
                        "plugins": ["test_light_structure", "test_light_interface"],
                        "input_model": "atom_array",
                        "execution_mode": "batched",
                        "worker_pool": "cpu",
                        "device_kind": "cpu",
                        "max_workers": None,
                        "cpu_threads_per_worker": 1,
                        "gpu_devices_per_worker": 0,
                        "planned_workers": 1,
                        "planned_cpu_threads": 1,
                        "planned_gpu_devices": 0,
                    },
                    {
                        "group_id": 1,
                        "depends_on_groups": [],
                        "wave": 1,
                        "plugins": ["test_heavy_failure"],
                        "input_model": "prepared_file",
                        "execution_mode": "isolated",
                        "worker_pool": "cpu",
                        "device_kind": "cpu",
                        "max_workers": None,
                        "cpu_threads_per_worker": 1,
                        "gpu_devices_per_worker": 0,
                        "planned_workers": 1,
                        "planned_cpu_threads": 1,
                        "planned_gpu_devices": 0,
                    },
                ],
            )
            self.assertEqual(
                metadata["plugin_execution"]["waves"],
                [
                    {"wave": 0, "group_ids": [0], "worker_pools": ["cpu"], "cpu_threads": 1, "gpu_devices": 0},
                    {"wave": 1, "group_ids": [1], "worker_pools": ["cpu"], "cpu_threads": 1, "gpu_devices": 0},
                ],
            )
            self.assertEqual(
                metadata["plugin_execution"]["scheduler_resources"],
                {
                    "single_job": {"cpu_threads": 1, "gpu_devices": 0},
                    "peak_cpu_threads": 1,
                    "peak_gpu_devices": 0,
                    "waves": [
                        {"wave": 0, "group_ids": [0], "worker_pools": ["cpu"], "cpu_threads": 1, "gpu_devices": 0},
                        {"wave": 1, "group_ids": [1], "worker_pools": ["cpu"], "cpu_threads": 1, "gpu_devices": 0},
                    ],
                    "submission_plan": {
                        "recommended_mode": "cpu_only",
                        "reason": "No GPU-enabled plugin waves are present, so CPU-only scheduling is sufficient.",
                        "stages": [
                            {
                                "stage": 0,
                                "worker_pools": ["cpu"],
                                "cpu_threads": 1,
                                "gpu_devices": 0,
                                "jobs": [
                                    {
                                        "job_id": "stage0-cpu",
                                        "stage": 0,
                                        "worker_pool": "cpu",
                                        "resource_class": "cpu_only",
                                        "device_kind": "cpu",
                                        "cpu_threads": 1,
                                        "gpu_devices": 0,
                                        "group_ids": [0],
                                        "plugins": ["test_light_structure", "test_light_interface"],
                                        "recommended_job": {"cpu_threads": 1, "gpu_devices": 0},
                                    }
                                ],
                            },
                            {
                                "stage": 1,
                                "worker_pools": ["cpu"],
                                "cpu_threads": 1,
                                "gpu_devices": 0,
                                "jobs": [
                                    {
                                        "job_id": "stage1-cpu",
                                        "stage": 1,
                                        "worker_pool": "cpu",
                                        "resource_class": "cpu_only",
                                        "device_kind": "cpu",
                                        "cpu_threads": 1,
                                        "gpu_devices": 0,
                                        "group_ids": [1],
                                        "plugins": ["test_heavy_failure"],
                                        "recommended_job": {"cpu_threads": 1, "gpu_devices": 0},
                                    }
                                ],
                            },
                        ],
                        "job_classes": [
                            {
                                "worker_pool": "cpu",
                                "resource_class": "cpu_only",
                                "device_kind": "cpu",
                                "peak_cpu_threads": 1,
                                "peak_gpu_devices": 0,
                                "stages": [0, 1],
                                "recommended_job": {"cpu_threads": 1, "gpu_devices": 0},
                            }
                        ],
                    },
                },
            )
            self.assertEqual(
                metadata["plugin_execution"]["runtime"],
                {
                    "cpu_workers": 1,
                    "gpu_workers": 0,
                    "gpu_devices": [],
                },
            )
            self.assertEqual(
                metadata["plugin_execution"]["plugins"]["test_heavy_failure"]["failure_policy"],
                "continue",
            )

    def test_plugin_execution_metadata_splits_cpu_and_gpu_groups(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            plugins=["test_light_structure", "test_gpu_structure", "test_light_interface"],
            cpu_workers=3,
            gpu_workers=2,
            gpu_devices=["0", "1"],
        )

        with mock.patch.dict(
            execute_module.PLUGIN_REGISTRY,
            {
                "test_light_structure": TestLightStructurePlugin(),
                "test_gpu_structure": TestGpuStructurePlugin(),
                "test_light_interface": TestLightInterfacePlugin(),
            },
            clear=True,
        ):
            metadata = execute_module.plugin_execution_metadata(cfg)

        self.assertEqual(
            metadata["groups"],
            [
                {
                    "group_id": 0,
                    "depends_on_groups": [],
                    "wave": 0,
                    "plugins": ["test_light_structure"],
                    "input_model": "atom_array",
                    "execution_mode": "batched",
                    "worker_pool": "cpu",
                    "device_kind": "cpu",
                    "max_workers": None,
                    "cpu_threads_per_worker": 1,
                    "gpu_devices_per_worker": 0,
                    "planned_workers": 3,
                    "planned_cpu_threads": 3,
                    "planned_gpu_devices": 0,
                },
                {
                    "group_id": 1,
                    "depends_on_groups": [],
                    "wave": 0,
                    "plugins": ["test_gpu_structure"],
                    "input_model": "atom_array",
                    "execution_mode": "batched",
                    "worker_pool": "gpu",
                    "device_kind": "cuda",
                    "max_workers": None,
                    "cpu_threads_per_worker": 1,
                    "gpu_devices_per_worker": 1,
                    "planned_workers": 2,
                    "planned_cpu_threads": 2,
                    "planned_gpu_devices": 2,
                },
                {
                    "group_id": 2,
                    "depends_on_groups": [],
                    "wave": 1,
                    "plugins": ["test_light_interface"],
                    "input_model": "atom_array",
                    "execution_mode": "batched",
                    "worker_pool": "cpu",
                    "device_kind": "cpu",
                    "max_workers": None,
                    "cpu_threads_per_worker": 1,
                    "gpu_devices_per_worker": 0,
                    "planned_workers": 3,
                    "planned_cpu_threads": 3,
                    "planned_gpu_devices": 0,
                },
            ],
        )
        self.assertEqual(
            metadata["waves"],
            [
                {"wave": 0, "group_ids": [0, 1], "worker_pools": ["cpu", "gpu"], "cpu_threads": 5, "gpu_devices": 2},
                {"wave": 1, "group_ids": [2], "worker_pools": ["cpu"], "cpu_threads": 3, "gpu_devices": 0},
            ],
        )
        self.assertEqual(
            metadata["scheduler_resources"],
            {
                "single_job": {"cpu_threads": 5, "gpu_devices": 2},
                "peak_cpu_threads": 5,
                "peak_gpu_devices": 2,
                "waves": [
                    {"wave": 0, "group_ids": [0, 1], "worker_pools": ["cpu", "gpu"], "cpu_threads": 5, "gpu_devices": 2},
                    {"wave": 1, "group_ids": [2], "worker_pools": ["cpu"], "cpu_threads": 3, "gpu_devices": 0},
                ],
                "submission_plan": {
                    "recommended_mode": "split_by_stage",
                    "reason": "CPU-only and GPU-enabled waves are both present, so staged submission can release GPU nodes during CPU-only phases.",
                    "stages": [
                        {
                            "stage": 0,
                            "worker_pools": ["cpu", "gpu"],
                            "cpu_threads": 5,
                            "gpu_devices": 2,
                            "jobs": [
                                {
                                    "job_id": "stage0-cpu",
                                    "stage": 0,
                                    "worker_pool": "cpu",
                                    "resource_class": "cpu_only",
                                    "device_kind": "cpu",
                                    "cpu_threads": 3,
                                    "gpu_devices": 0,
                                    "group_ids": [0],
                                    "plugins": ["test_light_structure"],
                                    "recommended_job": {"cpu_threads": 3, "gpu_devices": 0},
                                },
                                {
                                    "job_id": "stage0-gpu",
                                    "stage": 0,
                                    "worker_pool": "gpu",
                                    "resource_class": "gpu_enabled",
                                    "device_kind": "cuda",
                                    "cpu_threads": 2,
                                    "gpu_devices": 2,
                                    "group_ids": [1],
                                    "plugins": ["test_gpu_structure"],
                                    "recommended_job": {"cpu_threads": 2, "gpu_devices": 2},
                                },
                            ],
                        },
                        {
                            "stage": 1,
                            "worker_pools": ["cpu"],
                            "cpu_threads": 3,
                            "gpu_devices": 0,
                            "jobs": [
                                {
                                    "job_id": "stage1-cpu",
                                    "stage": 1,
                                    "worker_pool": "cpu",
                                    "resource_class": "cpu_only",
                                    "device_kind": "cpu",
                                    "cpu_threads": 3,
                                    "gpu_devices": 0,
                                    "group_ids": [2],
                                    "plugins": ["test_light_interface"],
                                    "recommended_job": {"cpu_threads": 3, "gpu_devices": 0},
                                }
                            ],
                        },
                    ],
                    "job_classes": [
                        {
                            "worker_pool": "cpu",
                            "resource_class": "cpu_only",
                            "device_kind": "cpu",
                            "peak_cpu_threads": 3,
                            "peak_gpu_devices": 0,
                            "stages": [0, 1],
                            "recommended_job": {"cpu_threads": 3, "gpu_devices": 0},
                        },
                        {
                            "worker_pool": "gpu",
                            "resource_class": "gpu_enabled",
                            "device_kind": "cuda",
                            "peak_cpu_threads": 2,
                            "peak_gpu_devices": 2,
                            "stages": [0],
                            "recommended_job": {"cpu_threads": 2, "gpu_devices": 2},
                        },
                    ],
                },
            },
        )
        self.assertEqual(
            metadata["runtime"],
            {
                "cpu_workers": 3,
                "gpu_workers": 2,
                "gpu_devices": ["0", "1"],
            },
        )
        self.assertEqual(metadata["plugins"]["test_gpu_structure"]["worker_pool"], "gpu")
        self.assertEqual(metadata["plugins"]["test_gpu_structure"]["device_kind"], "cuda")

    def test_plugin_execution_metadata_pushes_dependent_gpu_group_to_later_wave(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            plugins=["test_light_structure", "test_dependent_gpu"],
            cpu_workers=2,
            gpu_workers=1,
            gpu_devices=["0"],
        )

        with mock.patch.dict(
            execute_module.PLUGIN_REGISTRY,
            {
                "test_light_structure": TestLightStructurePlugin(),
                "test_dependent_gpu": TestDependentGpuPlugin(),
            },
            clear=True,
        ):
            metadata = execute_module.plugin_execution_metadata(cfg)

        self.assertEqual(
            metadata["groups"],
            [
                {
                    "group_id": 0,
                    "depends_on_groups": [],
                    "wave": 0,
                    "plugins": ["test_light_structure"],
                    "input_model": "atom_array",
                    "execution_mode": "batched",
                    "worker_pool": "cpu",
                    "device_kind": "cpu",
                    "max_workers": None,
                    "cpu_threads_per_worker": 1,
                    "gpu_devices_per_worker": 0,
                    "planned_workers": 2,
                    "planned_cpu_threads": 2,
                    "planned_gpu_devices": 0,
                },
                {
                    "group_id": 1,
                    "depends_on_groups": [0],
                    "wave": 1,
                    "plugins": ["test_dependent_gpu"],
                    "input_model": "atom_array",
                    "execution_mode": "batched",
                    "worker_pool": "gpu",
                    "device_kind": "cuda",
                    "max_workers": None,
                    "cpu_threads_per_worker": 1,
                    "gpu_devices_per_worker": 1,
                    "planned_workers": 1,
                    "planned_cpu_threads": 1,
                    "planned_gpu_devices": 1,
                },
            ],
        )
        self.assertEqual(
            metadata["waves"],
            [
                {"wave": 0, "group_ids": [0], "worker_pools": ["cpu"], "cpu_threads": 2, "gpu_devices": 0},
                {"wave": 1, "group_ids": [1], "worker_pools": ["gpu"], "cpu_threads": 1, "gpu_devices": 1},
            ],
        )
        self.assertEqual(
            metadata["scheduler_resources"]["submission_plan"],
            {
                "recommended_mode": "split_by_stage",
                "reason": "CPU-only and GPU-enabled waves are both present, so staged submission can release GPU nodes during CPU-only phases.",
                "stages": [
                    {
                        "stage": 0,
                        "worker_pools": ["cpu"],
                        "cpu_threads": 2,
                        "gpu_devices": 0,
                        "jobs": [
                            {
                                "job_id": "stage0-cpu",
                                "stage": 0,
                                "worker_pool": "cpu",
                                "resource_class": "cpu_only",
                                "device_kind": "cpu",
                                "cpu_threads": 2,
                                "gpu_devices": 0,
                                "group_ids": [0],
                                "plugins": ["test_light_structure"],
                                "recommended_job": {"cpu_threads": 2, "gpu_devices": 0},
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
                                "stage": 1,
                                "worker_pool": "gpu",
                                "resource_class": "gpu_enabled",
                                "device_kind": "cuda",
                                "cpu_threads": 1,
                                "gpu_devices": 1,
                                "group_ids": [1],
                                "plugins": ["test_dependent_gpu"],
                                "recommended_job": {"cpu_threads": 1, "gpu_devices": 1},
                            }
                        ],
                    },
                ],
                "job_classes": [
                    {
                        "worker_pool": "cpu",
                        "resource_class": "cpu_only",
                        "device_kind": "cpu",
                        "peak_cpu_threads": 2,
                        "peak_gpu_devices": 0,
                        "stages": [0],
                        "recommended_job": {"cpu_threads": 2, "gpu_devices": 0},
                    },
                    {
                        "worker_pool": "gpu",
                        "resource_class": "gpu_enabled",
                        "device_kind": "cuda",
                        "peak_cpu_threads": 1,
                        "peak_gpu_devices": 1,
                        "stages": [1],
                        "recommended_job": {"cpu_threads": 1, "gpu_devices": 1},
                    },
                ],
            },
        )

    def test_plugin_execution_metadata_accounts_for_cpu_thread_weights(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            plugins=["test_wide_cpu"],
            cpu_workers=3,
        )

        with mock.patch.dict(
            execute_module.PLUGIN_REGISTRY,
            {"test_wide_cpu": TestWideCpuPlugin()},
            clear=True,
        ):
            metadata = execute_module.plugin_execution_metadata(cfg)

        self.assertEqual(
            metadata["groups"],
            [
                {
                    "group_id": 0,
                    "depends_on_groups": [],
                    "wave": 0,
                    "plugins": ["test_wide_cpu"],
                    "input_model": "atom_array",
                    "execution_mode": "batched",
                    "worker_pool": "cpu",
                    "device_kind": "cpu",
                    "max_workers": None,
                    "cpu_threads_per_worker": 2,
                    "gpu_devices_per_worker": 0,
                    "planned_workers": 3,
                    "planned_cpu_threads": 6,
                    "planned_gpu_devices": 0,
                }
            ],
        )
        self.assertEqual(
            metadata["scheduler_resources"]["single_job"],
            {"cpu_threads": 6, "gpu_devices": 0},
        )
        self.assertEqual(
            metadata["scheduler_resources"]["submission_plan"]["recommended_mode"],
            "cpu_only",
        )

    def test_plugin_execution_metadata_routes_abepitope_to_gpu_pool(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            plugins=["abepitope_score"],
            gpu_workers=1,
            gpu_devices=["0"],
            plugin_params={"abepitope_score": {"device": "auto"}},
        )

        metadata = execute_module.plugin_execution_metadata(cfg)

        self.assertEqual(
            metadata["groups"],
            [
                {
                    "group_id": 0,
                    "depends_on_groups": [],
                    "wave": 0,
                    "plugins": ["abepitope_score"],
                    "input_model": "hybrid",
                    "execution_mode": "isolated",
                    "worker_pool": "gpu",
                    "device_kind": "cuda",
                    "max_workers": None,
                    "cpu_threads_per_worker": 1,
                    "gpu_devices_per_worker": 1,
                    "planned_workers": 1,
                    "planned_cpu_threads": 1,
                    "planned_gpu_devices": 1,
                }
            ],
        )
        self.assertEqual(metadata["plugins"]["abepitope_score"]["worker_pool"], "gpu")
        self.assertEqual(metadata["plugins"]["abepitope_score"]["device_kind"], "cuda")

    def test_abepitope_worker_receives_scheduler_assigned_device(self) -> None:
        plugin = AbEpiTopeScorePlugin()
        seen_cmds: list[list[str]] = []

        def fake_popen(cmd, **kwargs):
            seen_cmds.append(list(cmd))
            return _FakeAbEpiTopeProcess()

        with mock.patch("minimum_atw.plugins.pdb.calculation.interface_analysis.abepitope_score.subprocess.Popen", side_effect=fake_popen):
            proc = plugin._get_worker(device="cuda:1")
            self.assertIsNotNone(proc)
            same_proc = plugin._get_worker(device="cuda:1")
            self.assertIs(proc, same_proc)
            plugin._shutdown_worker()

        self.assertEqual(len(seen_cmds), 1)
        self.assertEqual(seen_cmds[0][-2:], ["--device", "cuda:1"])

    def test_cpu_worker_pool_dispatches_through_parallel_executor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_execution_test_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            input_dir.mkdir()
            self._write_complexes(input_dir, count=2)

            cfg = Config(
                input_dir=str(input_dir),
                out_dir=str(out_dir),
                roles={"binder": ["A"], "target": ["B"]},
                interface_pairs=[("binder", "target")],
                plugins=["test_light_structure", "test_light_interface"],
                keep_intermediate_outputs=True,
                cpu_workers=2,
            )

            prepare_outputs(cfg)

            with (
                mock.patch.dict(
                    execute_module.PLUGIN_REGISTRY,
                    {
                        "test_light_structure": TestLightStructurePlugin(),
                        "test_light_interface": TestLightInterfacePlugin(),
                    },
                    clear=True,
                ),
                mock.patch("minimum_atw.core._execute.concurrent.futures.ProcessPoolExecutor", _PermissionErrorProcessPool),
                mock.patch("minimum_atw.core._execute._execute_plugin_group_serial", side_effect=AssertionError("serial dispatcher should not run")),
            ):
                plugin_counts = run_plugins(cfg, cfg.plugins)
                merge_outputs(cfg)

            self.assertEqual(plugin_counts["structures"], 2)
            self.assertEqual(plugin_counts["interfaces"], 2)
            structures = read_pdb_grain(out_dir, "structure")
            interfaces = read_pdb_grain(out_dir, "interface")
            self.assertEqual(sorted(structures["light_structure__signal"].dropna().astype(int).tolist()), [11, 11])
            self.assertEqual(len(interfaces["light_interface__label"].dropna()), 2)

    def test_gpu_worker_pool_assigns_distinct_device_slots(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_execution_test_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            input_dir.mkdir()
            self._write_complexes(input_dir, count=2)

            cfg = Config(
                input_dir=str(input_dir),
                out_dir=str(out_dir),
                roles={"binder": ["A"], "target": ["B"]},
                interface_pairs=[("binder", "target")],
                plugins=["test_gpu_structure"],
                keep_intermediate_outputs=True,
                gpu_workers=2,
                gpu_devices=["0", "1"],
                plugin_params={"test_gpu_structure": {"device": "auto"}},
            )

            prepare_outputs(cfg)

            with (
                mock.patch.dict(
                    execute_module.PLUGIN_REGISTRY,
                    {"test_gpu_structure": TestGpuStructurePlugin()},
                    clear=True,
                ),
                mock.patch("minimum_atw.core._execute.concurrent.futures.ProcessPoolExecutor", _PermissionErrorProcessPool),
                mock.patch("minimum_atw.core._execute._execute_plugin_group_serial", side_effect=AssertionError("serial dispatcher should not run")),
            ):
                plugin_counts = run_plugins(cfg, cfg.plugins)
                merge_outputs(cfg)

            self.assertEqual(plugin_counts["structures"], 2)
            structures = read_pdb_grain(out_dir, "structure")
            self.assertEqual(
                set(structures["gpu_structure__device"].dropna().astype(str).tolist()),
                {"cuda:0", "cuda:1"},
            )

    def test_run_plugins_executes_independent_cpu_and_gpu_groups_in_same_wave(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_execution_test_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            input_dir.mkdir()
            self._write_complexes(input_dir, count=1)

            cfg = Config(
                input_dir=str(input_dir),
                out_dir=str(out_dir),
                roles={"binder": ["A"], "target": ["B"]},
                interface_pairs=[("binder", "target")],
                plugins=["test_light_structure", "test_gpu_structure"],
                keep_intermediate_outputs=True,
                cpu_workers=1,
                gpu_workers=1,
                gpu_devices=["0"],
            )

            prepare_outputs(cfg)
            barrier = threading.Barrier(2, timeout=1.0)
            seen_groups: list[tuple[str, ...]] = []
            original_execute_group = execute_module._execute_plugin_group

            def wrapped_execute_group(runtime_cfg, manifest, group, states, context_cache):
                seen_groups.append(tuple(spec.name for spec in group))
                barrier.wait()
                return original_execute_group(runtime_cfg, manifest, group, states, context_cache)

            with mock.patch.dict(
                execute_module.PLUGIN_REGISTRY,
                {
                    "test_light_structure": TestLightStructurePlugin(),
                    "test_gpu_structure": TestGpuStructurePlugin(),
                },
                clear=True,
            ), mock.patch("minimum_atw.core._execute._execute_plugin_group", side_effect=wrapped_execute_group):
                run_plugins(cfg, cfg.plugins)

            self.assertEqual(
                sorted(seen_groups),
                [("test_gpu_structure",), ("test_light_structure",)],
            )


if __name__ == "__main__":
    unittest.main()
