from __future__ import annotations

import io
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import pandas as pd
    import yaml
    from minimum_atw.cli import _load_config
    from minimum_atw.core.config import Config
    from minimum_atw.externals.abepitope_runner import _load_output_metrics
    from minimum_atw.core.pipeline import run_pipeline
    from minimum_atw.runtime.workspace import prepare_context
    from minimum_atw.plugins.pdb.calculation.interface_analysis.abepitope_score import (
        AbEpiTopeScorePlugin,
        _abepitope_chain_hints,
        _backend_cache_key,
        _runner_script_path,
    )
    from minimum_atw.tests.helpers import read_pdb_grain
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "pydantic", "yaml", "pandas", "pyarrow"}:
        raise
    pd = None
    yaml = None
    _load_config = None
    Config = None
    _load_output_metrics = None
    run_pipeline = None
    prepare_context = None
    AbEpiTopeScorePlugin = None
    _abepitope_chain_hints = None
    _backend_cache_key = None
    _runner_script_path = None
    read_pdb_grain = None


@unittest.skipIf(run_pipeline is None, "pipeline dependencies are not installed")
class AbEpiTopePluginTests(unittest.TestCase):
    def _toy_abag_context(self, root: Path):
        structure_path = root / "toy_abag.pdb"
        structure_path.write_text(
            textwrap.dedent(
                """\
                ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                ATOM      3  N   SER B   1       0.000   0.000   3.000  1.00 20.00           N
                ATOM      4  CA  SER B   1       1.200   0.000   3.000  1.00 20.00           C
                ATOM      5  N   TYR C   1       0.000   0.000   3.500  1.00 20.00           N
                ATOM      6  CA  TYR C   1       1.200   0.000   3.500  1.00 20.00           C
                TER
                END
                """
            )
        )
        cfg = Config(
            input_dir=str(root),
            out_dir=str(root / "out"),
            roles={"antigen": ["A"], "vh": ["C"], "vl": ["B"], "antibody": ["B", "C"]},
            interface_pairs=[("antibody", "antigen")],
            numbering_roles=["vh", "vl"],
        )
        return prepare_context(structure_path, structure_path, cfg)

    def test_abepitope_runner_script_path_exists(self) -> None:
        self.assertTrue(_runner_script_path().exists())
        self.assertEqual(_runner_script_path().name, "abepitope_runner.py")

    def test_abepitope_plugin_writes_interface_scores(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_abepitope_test_") as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "input"
            out_dir = root / "out"
            config_path = root / "config.yaml"
            input_dir.mkdir()

            (input_dir / "toy_interface.pdb").write_text(
                textwrap.dedent(
                    """\
                    ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                    ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                    ATOM      3  N   ALA B   2       0.000   0.000   3.000  1.00 20.00           N
                    ATOM      4  CA  ALA B   2       1.200   0.000   3.000  1.00 20.00           C
                    TER
                    END
                    """
                )
            )

            config_path.write_text(
                yaml.safe_dump(
                    {
                        "input_dir": str(input_dir),
                        "out_dir": str(out_dir),
                        "roles": {"antibody": ["A"], "antigen": ["B"]},
                        "interface_pairs": [["antibody", "antigen"]],
                        "plugins": ["abepitope_score"],
                        "abepitope_atom_radius": 4.5,
                    },
                    sort_keys=False,
                )
            )

            cfg = _load_config(str(config_path))
            with (
                patch.object(AbEpiTopeScorePlugin, "available", return_value=(True, "")),
                patch.object(
                    AbEpiTopeScorePlugin,
                    "_run_backend",
                    return_value={"score": 0.75, "target_score": 0.55},
                ),
            ):
                run_pipeline(cfg)

            interfaces = read_pdb_grain(out_dir, "interface")
            row = interfaces.iloc[0]
            self.assertEqual(float(row["abepitope__atom_radius"]), 4.5)
            self.assertEqual(float(row["abepitope__score"]), 0.75)
            self.assertEqual(float(row["abepitope__target_score"]), 0.55)

    def test_abepitope_preflight_requires_hmmsearch(self) -> None:
        plugin = AbEpiTopeScorePlugin()
        with (
            patch("minimum_atw.plugins.pdb.calculation.interface_analysis.abepitope_score.find_spec", return_value=object()),
            patch("minimum_atw.plugins.pdb.calculation.interface_analysis.abepitope_score._resolve_hmmsearch", return_value=None),
        ):
            available, message = plugin.available(None)

        self.assertFalse(available)
        self.assertIn("hmmsearch", message)

    def test_abepitope_chain_hints_are_derived_from_roles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_abepitope_ctx_") as tmp_dir:
            ctx = self._toy_abag_context(Path(tmp_dir))

        hints = _abepitope_chain_hints(
            ctx,
            left_role="antibody",
            right_role="antigen",
            left=ctx.roles["antibody"],
            right=ctx.roles["antigen"],
        )

        self.assertEqual(
            hints,
            {
                "heavy_chain_ids": ["C"],
                "light_chain_ids": ["B"],
                "antigen_chain_ids": ["A"],
            },
        )

    def test_abepitope_preflight_allows_role_derived_hints_without_hmmsearch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_abepitope_ctx_") as tmp_dir:
            ctx = self._toy_abag_context(Path(tmp_dir))

        plugin = AbEpiTopeScorePlugin()
        with (
            patch("minimum_atw.plugins.pdb.calculation.interface_analysis.abepitope_score.find_spec", return_value=object()),
            patch("minimum_atw.plugins.pdb.calculation.interface_analysis.abepitope_score._resolve_hmmsearch", return_value=None),
        ):
            available, message = plugin.available(ctx)

        self.assertTrue(available)
        self.assertEqual(message, "")

    def test_abepitope_cache_key_depends_on_structure_content(self) -> None:
        pdb_one = textwrap.dedent(
            """\
            ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
            END
            """
        )
        pdb_two = textwrap.dedent(
            """\
            ATOM      1  N   GLY A   1       8.000   0.000   0.000  1.00 20.00           N
            END
            """
        )

        key_one = _backend_cache_key(pdb_one, atom_radius=4.0)
        self.assertEqual(key_one, _backend_cache_key(pdb_one, atom_radius=4.0))
        self.assertNotEqual(key_one, _backend_cache_key(pdb_two, atom_radius=4.0))
        self.assertNotEqual(key_one, _backend_cache_key(pdb_one, atom_radius=4.5))

    def test_abepitope_output_parser_ignores_non_finite_scores(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_abepitope_metrics_") as tmp_dir:
            out_dir = Path(tmp_dir)
            (out_dir / "output.csv").write_text(
                "FileName,AbEpiScore-1.0,AbEpiTarget-1.0\n"
                "pair.pdb,nan,0.55\n"
            )

            metrics = _load_output_metrics(out_dir)

        self.assertEqual(metrics, {"target_score": 0.55})

    def test_abepitope_plugin_caches_final_metrics_without_restarting_worker(self) -> None:
        class _FakeProcess:
            def __init__(self) -> None:
                self.stdin = io.StringIO()
                self.stdout = io.StringIO('{"ok": true, "metrics": {"score": 0.42}}\n')
                self.returncode = None

            def poll(self):
                return None

        plugin = AbEpiTopeScorePlugin()
        fake_process = _FakeProcess()

        with patch.object(plugin, "_get_worker", return_value=fake_process) as get_worker:
            first = plugin._run_backend("MODEL", seq_hash="same-key", atom_radius=4.0, device="cpu")
            second = plugin._run_backend("MODEL", seq_hash="same-key", atom_radius=4.0, device="cpu")

        self.assertEqual(first, {"score": 0.42})
        self.assertEqual(second, {"score": 0.42})
        self.assertEqual(get_worker.call_count, 1)


if __name__ == "__main__":
    unittest.main()
