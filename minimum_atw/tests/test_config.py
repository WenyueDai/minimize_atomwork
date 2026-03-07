from __future__ import annotations

import unittest

try:
    from minimum_atw.core.config import Config
except ModuleNotFoundError as exc:
    if exc.name != "pydantic":
        raise
    Config = None


@unittest.skipIf(Config is None, "pydantic is not installed")
class ConfigTests(unittest.TestCase):
    def test_extension_lists_are_trimmed_and_deduplicated(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            plugins=[" identity ", "identity", "", "role_stats"],
            quality_controls=[" chain_continuity ", "chain_continuity"],
            structure_manipulations=[" center_on_origin ", "center_on_origin"],
            dataset_quality_controls=[" dataset_schema ", "dataset_schema"],
            dataset_manipulations=[" superimpose_homology ", "superimpose_homology"],
            manipulations=[" center_on_origin ", "center_on_origin"],
            dataset_analyses=[" interface_summary ", "interface_summary"],
            dataset_analysis_mode=" BOTH ",
        )

        self.assertEqual(cfg.plugins, ["identity", "role_stats"])
        self.assertEqual(cfg.quality_controls, ["chain_continuity"])
        self.assertEqual(cfg.structure_manipulations, ["center_on_origin"])
        self.assertEqual(cfg.dataset_quality_controls, ["dataset_schema"])
        self.assertEqual(cfg.dataset_manipulations, ["superimpose_homology"])
        self.assertEqual(cfg.manipulations, ["center_on_origin"])
        self.assertEqual(cfg.dataset_analyses, ["interface_summary"])
        self.assertEqual(cfg.dataset_analysis_mode, "both")

    def test_roles_and_interface_pairs_are_normalized(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            roles={" vh ": [" H ", "H", ""], "": ["X"]},
            interface_pairs=[(" vh ", " antigen "), ("vh", "antigen"), ("", "antigen")],
        )

        self.assertEqual(cfg.roles, {"vh": ["H"]})
        self.assertEqual(cfg.interface_pairs, [("vh", "antigen")])

    def test_numbering_options_are_normalized(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            numbering_scheme=" Chothia ",
            cdr_definition=" North ",
        )

        self.assertEqual(cfg.numbering_scheme, "chothia")
        self.assertEqual(cfg.cdr_definition, "north")

    def test_clash_options_are_normalized_and_validated(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            clash_scope=" Interface_Only ",
        )

        self.assertEqual(cfg.clash_distance, 2.0)
        self.assertEqual(cfg.clash_scope, "interface_only")

        with self.assertRaises(ValueError):
            Config(input_dir="/tmp/in", out_dir="/tmp/out", clash_distance=0)

        with self.assertRaises(ValueError):
            Config(input_dir="/tmp/in", out_dir="/tmp/out", clash_scope="local_only")

    def test_checkpoint_defaults_and_validation(self) -> None:
        cfg = Config(input_dir="/tmp/in", out_dir="/tmp/out")
        self.assertFalse(cfg.checkpoint_enabled)
        self.assertEqual(cfg.checkpoint_interval, 100)

        # interval must be positive
        with self.assertRaises(ValueError):
            Config(input_dir="/tmp/in", out_dir="/tmp/out", checkpoint_interval=0)

    def test_aho_requires_cdr_definition(self) -> None:
        with self.assertRaises(ValueError):
            Config(
                input_dir="/tmp/in",
                out_dir="/tmp/out",
                numbering_scheme="aho",
            )

    def test_rosetta_defaults_and_validation(self) -> None:
        cfg = Config(input_dir="/tmp/in", out_dir="/tmp/out")

        self.assertTrue(cfg.rosetta_pack_input)
        self.assertTrue(cfg.rosetta_pack_separated)
        self.assertTrue(cfg.rosetta_compute_packstat)
        self.assertTrue(cfg.rosetta_add_regular_scores_to_scorefile)
        self.assertFalse(cfg.rosetta_preprocess_with_score_jd2)
        self.assertIsNone(cfg.rosetta_packstat_oversample)
        self.assertEqual(cfg.rosetta_atomic_burial_cutoff, 0.01)
        self.assertEqual(cfg.rosetta_sasa_calculator_probe_radius, 1.4)
        self.assertEqual(cfg.rosetta_interface_cutoff, 8.0)

        with self.assertRaises(ValueError):
            Config(
                input_dir="/tmp/in",
                out_dir="/tmp/out",
                rosetta_packstat_oversample=0,
            )

    def test_rosetta_interface_targets_are_normalized(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            interface_pairs=[("binder", "target")],
            rosetta_interface_targets=[
                {
                    "left_role": " binder ",
                    "right_chains": [" A ", "A", "B"],
                }
            ],
        )

        target = cfg.rosetta_targets()[0]
        self.assertEqual(target.left_role, "binder")
        self.assertEqual(target.right_chains, ["A", "B"])
        self.assertEqual(target.pair, ("binder", "chains_A_B"))
        self.assertEqual(
            cfg.interface_pairs_for_outputs(),
            [("binder", "target"), ("binder", "chains_A_B")],
        )


if __name__ == "__main__":
    unittest.main()
