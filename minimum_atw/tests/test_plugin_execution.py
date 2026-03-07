from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

try:
    import pandas as pd
    from minimum_atw.core.config import Config
    from minimum_atw.core.pipeline import merge_outputs, prepare_outputs, run_plugins
    from minimum_atw.plugins.base import BasePlugin, InterfacePlugin
    from minimum_atw.tests.helpers import read_pdb_grain
    import minimum_atw.core._execute as execute_module
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "pydantic", "pandas", "pyarrow"}:
        raise
    pd = None
    Config = None
    read_pdb_grain = None


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


@unittest.skipIf(Config is None, "pipeline dependencies are not installed")
class PluginExecutionModelTests(unittest.TestCase):
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

            self.assertEqual(len(load_calls), 2)
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
                        "plugins": ["test_light_structure", "test_light_interface"],
                        "input_model": "atom_array",
                        "execution_mode": "batched",
                    },
                    {
                        "plugins": ["test_heavy_failure"],
                        "input_model": "prepared_file",
                        "execution_mode": "isolated",
                    },
                ],
            )
            self.assertEqual(
                metadata["plugin_execution"]["plugins"]["test_heavy_failure"]["failure_policy"],
                "continue",
            )


if __name__ == "__main__":
    unittest.main()
