from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from minimum_atw.core.config import Config
    from minimum_atw.plugins.base import Context
    from minimum_atw.plugins.pdb.calculation.interface_analysis.rosetta_interface import (
        RosettaInterfaceExamplePlugin,
        _build_fixedchains_pose,
        _build_interface_analyzer_command,
        _parse_scorefile,
    )
    from minimum_atw.plugins.pdb.rosetta_common import run_score_jd2 as _run_score_jd2
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "numpy", "pydantic"}:
        raise
    Config = None


@unittest.skipIf(Config is None, "rosetta plugin dependencies are not installed")
class RosettaInterfacePluginTests(unittest.TestCase):
    def _make_config(self, **overrides) -> Config:
        base = {
            "input_dir": "/tmp/in",
            "out_dir": "/tmp/out",
            "roles": {"binder": ["A"], "target": ["B"]},
            "interface_pairs": [("binder", "target")],
        }
        base.update(overrides)
        return Config(**base)

    def test_interface_analyzer_command_respects_fixedchains_and_settings(self) -> None:
        cfg = self._make_config(
            rosetta_pack_input=False,
            rosetta_pack_separated=True,
            rosetta_compute_packstat=True,
            rosetta_packstat_oversample=100,
            rosetta_atomic_burial_cutoff=0.02,
            rosetta_sasa_calculator_probe_radius=1.5,
            rosetta_interface_cutoff=9.0,
        )

        command = _build_interface_analyzer_command(
            "InterfaceAnalyzer.static.linuxgccrelease",
            "/rosetta/database",
            Path("/tmp/input.pdb"),
            Path("/tmp/interface.sc"),
            ["A", "B"],
            cfg,
        )

        self.assertEqual(command[0], "InterfaceAnalyzer.static.linuxgccrelease")
        self.assertEqual(command[command.index("-fixedchains") + 1: command.index("-use_input_sc")], ["A", "B"])
        self.assertEqual(command[command.index("-pack_input") + 1], "false")
        self.assertEqual(command[command.index("-pack_separated") + 1], "false")
        self.assertEqual(command[command.index("-compute_packstat") + 1], "true")
        self.assertEqual(command[command.index("-add_regular_scores_to_scorefile") + 1], "true")
        self.assertEqual(command[command.index("-atomic_burial_cutoff") + 1], "0.02")
        self.assertEqual(command[command.index("-sasa_calculator_probe_radius") + 1], "1.5")
        self.assertEqual(command[command.index("-pose_metrics::interface_cutoff") + 1], "9.0")
        self.assertEqual(command[command.index("-packstat::oversample") + 1], "100")

    def test_score_jd2_command_uses_expected_fixup_flags(self) -> None:
        captured: list[list[str]] = []

        def fake_run(command, **_kwargs):
            captured.append(list(command))
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with mock.patch("minimum_atw.plugins.pdb.rosetta_common.subprocess.run", side_effect=fake_run):
            _run_score_jd2(
                executable="score_jd2.static.linuxgccrelease",
                database="/rosetta/database",
                input_path=Path("/tmp/input.pdb"),
                score_path=Path("/tmp/dummy.sc"),
                output_pdb_dir=Path("/tmp/preprocessed"),
            )

        self.assertEqual(len(captured), 1)
        command = captured[0]
        self.assertEqual(command[0], "score_jd2.static.linuxgccrelease")
        self.assertIn("-ignore_unrecognized_res", command)
        self.assertEqual(command[command.index("-no_optH") + 1], "false")
        self.assertIn("-out:pdb", command)
        self.assertEqual(command[command.index("-out:path:all") + 1], "/tmp/preprocessed")

    def test_parse_scorefile_retains_extended_interface_metrics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_rosetta_test_") as tmp_dir:
            score_path = Path(tmp_dir) / "interface.sc"
            score_path.write_text(
                "\n".join(
                    [
                        "SCORE: total_score dG_separated dG_separated/dSASAx100 dG_cross dG_cross/dSASAx100 cen_dG dSASA_int per_residue_energy_int side1_score side2_score nres_all side1_normalized side2_normalized complex_normalized hbond_E_fraction delta_unsatHbonds hbonds_int nres_int description",
                        "SCORE: 0 -3.0 -1.2 -2.5 -0.9 -1.0 120 -0.3 -10 -12 55 -0.4 -0.5 -0.2 0.35 2 4 11 pose",
                    ]
                )
                + "\n"
            )

            parsed = _parse_scorefile(score_path)

        self.assertEqual(parsed["interface_dg_separated"], -3.0)
        self.assertEqual(parsed["interface_dg_separated_per_dsasa_x100"], -1.2)
        self.assertEqual(parsed["interface_dg_cross"], -2.5)
        self.assertEqual(parsed["interface_dg_cross_per_dsasa_x100"], -0.9)
        self.assertEqual(parsed["interface_cen_dg"], -1.0)
        self.assertEqual(parsed["interface_per_residue_energy"], -0.3)
        self.assertEqual(parsed["interface_side1_score"], -10.0)
        self.assertEqual(parsed["interface_side2_score"], -12.0)
        self.assertEqual(parsed["complex_nres"], 55)
        self.assertEqual(parsed["interface_side1_normalized"], -0.4)
        self.assertEqual(parsed["interface_side2_normalized"], -0.5)
        self.assertEqual(parsed["complex_normalized"], -0.2)
        self.assertEqual(parsed["interface_hbond_e_fraction"], 0.35)

    def test_fixedchains_pose_preserves_multichain_groups(self) -> None:
        class FakeChain:
            def __init__(self, chain_id):
                self.chain_id = [chain_id]

            def copy(self):
                return FakeChain(self.chain_id[0])

        with mock.patch("biotite.structure.concatenate", side_effect=lambda arrays: arrays):
            pose, fixedchains = _build_fixedchains_pose(
                [FakeChain("H"), FakeChain("L")],
                [FakeChain("A")],
            )

        self.assertEqual(fixedchains, ["A", "B"])
        self.assertEqual([chain.chain_id[0] for chain in pose], ["A", "B", "C"])

    def test_available_uses_configured_rosetta_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_rosetta_test_") as tmp_dir:
            root = Path(tmp_dir)
            executable = root / "InterfaceAnalyzer.static.linuxgccrelease"
            score_jd2 = root / "score_jd2.static.linuxgccrelease"
            database = root / "database"
            executable.write_text("")
            score_jd2.write_text("")
            database.mkdir()

            cfg = self._make_config(
                rosetta_executable=str(executable),
                rosetta_database=str(database),
                rosetta_preprocess_with_score_jd2=True,
                rosetta_score_jd2_executable=str(score_jd2),
            )
            ctx = Context(path="/tmp/source.pdb", assembly_id="1", aa=None, role_map={}, config=cfg)

            available, message = RosettaInterfaceExamplePlugin().available(ctx)

            self.assertTrue(available, message)
            self.assertEqual(message, "")

    def test_run_supports_chain_selected_targets_and_continues_after_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_rosetta_test_") as tmp_dir:
            root = Path(tmp_dir)
            executable = root / "InterfaceAnalyzer.static.linuxgccrelease"
            score_jd2 = root / "score_jd2.static.linuxgccrelease"
            database = root / "database"
            executable.write_text("")
            score_jd2.write_text("")
            database.mkdir()

            cfg = self._make_config(
                rosetta_executable=str(executable),
                rosetta_database=str(database),
                rosetta_preprocess_with_score_jd2=True,
                rosetta_score_jd2_executable=str(score_jd2),
                rosetta_interface_targets=[
                    {
                        "pair": ["ab", "ag"],
                        "left_chains": ["H", "L"],
                        "right_chains": ["A"],
                    },
                    {
                        "pair": ["binder", "target"],
                        "left_role": "binder",
                        "right_role": "target",
                    },
                ],
            )
            ctx = Context(
                path="/tmp/source.pdb",
                assembly_id="1",
                aa=None,
                role_map={"binder": ("A",), "target": ("B",)},
                config=cfg,
                chains={"H": [1], "L": [1], "A": [1], "B": [1]},
            )
            plugin = RosettaInterfaceExamplePlugin()

            score_jd2_calls = 0
            interface_calls = 0
            interface_inputs: list[str] = []
            fixedchains_args: list[list[str]] = []

            def fake_run(command, capture_output, text, check):
                nonlocal score_jd2_calls, interface_calls
                executable_name = Path(command[0]).name
                if executable_name.startswith("score_jd2"):
                    score_jd2_calls += 1
                    output_dir = Path(command[command.index("-out:path:all") + 1])
                    output_dir.mkdir(parents=True, exist_ok=True)
                    (output_dir / f"pair_{score_jd2_calls:02d}_0001.pdb").write_text("MODEL\nEND\n")
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

                interface_calls += 1
                interface_inputs.append(command[command.index("-in:file:s") + 1])
                fixedchains_args.append(command[command.index("-fixedchains") + 1: command.index("-use_input_sc")])
                if interface_calls == 1:
                    raise subprocess.CalledProcessError(1, command, stderr="first pair failed")

                score_path = Path(command[command.index("-out:file:score_only") + 1])
                score_path.write_text(
                    "\n".join(
                        [
                            "SCORE: total_score interface_dG dG_separated dSASA_int dSASA_hphobic dSASA_polar packstat sc_value delta_unsatHbonds hbonds_int nres_int description",
                            "SCORE: 0 -1.5 -2.5 100 60 40 0.55 0.67 2 4 12 pose",
                        ]
                    )
                    + "\n"
                )
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with (
                mock.patch(
                    "minimum_atw.plugins.pdb.calculation.interface_analysis.rosetta_interface.save_structure",
                    side_effect=lambda path, atoms: Path(path).write_text("ATOM\nEND\n"),
                ),
                mock.patch(
                    "minimum_atw.plugins.pdb.calculation.interface_analysis.rosetta_interface._build_fixedchains_pose",
                    side_effect=[
                        (object(), ["A", "B"]),
                        (object(), ["A"]),
                    ],
                ),
                mock.patch("minimum_atw.plugins.pdb.calculation.interface_analysis.rosetta_interface.subprocess.run", side_effect=fake_run),
                mock.patch("builtins.print") as mock_print,
            ):
                rows = list(plugin.run(ctx))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["pair"], "binder__target")
            self.assertAlmostEqual(rows[0]["interface_dg"], -1.5)
            self.assertEqual(score_jd2_calls, 2)
            self.assertEqual(interface_calls, 2)
            self.assertTrue(interface_inputs)
            self.assertTrue(all(Path(path).parent.name == "score_jd2" for path in interface_inputs))
            self.assertEqual(fixedchains_args, [["A", "B"], ["A"]])
            mock_print.assert_called_once()


if __name__ == "__main__":
    unittest.main()
