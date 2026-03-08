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
            manipulations=[
                {"name": "chain_continuity", "grain": "pdb"},
                {"name": "chain_continuity", "grain": "pdb"},
                {"name": "center_on_origin", "grain": "pdb"},
                {"name": "center_on_origin", "grain": "pdb"},
            ],
            dataset_analyses=[" interface_summary ", "interface_summary"],
            dataset_analysis_mode=" BOTH ",
        )

        self.assertEqual(cfg.plugins, ["identity", "role_stats"])
        self.assertEqual(cfg.manipulations, [
            {"name": "chain_continuity", "grain": "pdb"},
            {"name": "center_on_origin", "grain": "pdb"},
        ])
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

    def test_output_names_are_normalized_and_validated(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            pdb_output_name=" 20250212_pdb ",
            dataset_output_name=" 20250212_dataset.parquet ",
        )

        self.assertEqual(cfg.pdb_output_name, "20250212_pdb.parquet")
        self.assertEqual(cfg.dataset_output_name, "20250212_dataset.parquet")
        self.assertNotIn("pdb_output_name", cfg.merge_compatibility())
        self.assertNotIn("dataset_output_name", cfg.merge_compatibility())

        with self.assertRaises(ValueError):
            Config(
                input_dir="/tmp/in",
                out_dir="/tmp/out",
                pdb_output_name="subdir/custom.parquet",
            )

        with self.assertRaises(ValueError):
            Config(
                input_dir="/tmp/in",
                out_dir="/tmp/out",
                pdb_output_name="same.parquet",
                dataset_output_name="same.parquet",
            )

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
        self.assertFalse(cfg.cleanup_prepared_after_dataset_analysis)
        self.assertIsNone(cfg.chunk_cpu_capacity)
        self.assertEqual(cfg.cpu_workers, 1)
        self.assertEqual(cfg.gpu_workers, 0)
        self.assertEqual(cfg.gpu_devices, [])

        # interval must be positive
        with self.assertRaises(ValueError):
            Config(input_dir="/tmp/in", out_dir="/tmp/out", checkpoint_interval=0)

    def test_worker_pool_runtime_options_are_normalized(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            chunk_cpu_capacity=" 16 ",
            cpu_workers=" 4 ",
            gpu_workers=" 2 ",
            gpu_devices=[" 0 ", "cuda:1", "0", ""],
        )

        self.assertEqual(cfg.chunk_cpu_capacity, 16)
        self.assertEqual(cfg.cpu_workers, 4)
        self.assertEqual(cfg.gpu_workers, 2)
        self.assertEqual(cfg.gpu_devices, ["0", "cuda:1"])
        self.assertNotIn("chunk_cpu_capacity", cfg.merge_compatibility())
        self.assertNotIn("cpu_workers", cfg.merge_compatibility())
        self.assertNotIn("gpu_workers", cfg.merge_compatibility())
        self.assertNotIn("gpu_devices", cfg.merge_compatibility())

        with self.assertRaises(ValueError):
            Config(input_dir="/tmp/in", out_dir="/tmp/out", chunk_cpu_capacity=0)

        with self.assertRaises(ValueError):
            Config(input_dir="/tmp/in", out_dir="/tmp/out", cpu_workers=0)

        with self.assertRaises(ValueError):
            Config(input_dir="/tmp/in", out_dir="/tmp/out", gpu_workers=-1)

    def test_slurm_options_are_normalized_and_excluded_from_merge_compatibility(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            slurm={
                "chunk_size": " 50 ",
                "plan_dir": " ~/plans/example ",
                "workdir": " ~/minimum_atomworks ",
                "python_bin": " ~/miniconda3/envs/atw_pp/bin/python ",
                "mode": " AUTO ",
                "array_limit": " 3 ",
                "log_dir": " ~/logs/minimum_atw ",
                "sbatch_common_args": [" --account=my_lab ", "", "--qos=normal"],
                "sbatch_gpu_args": [" --partition=gpu "],
            },
        )

        self.assertEqual(cfg.slurm.chunk_size, 50)
        self.assertEqual(cfg.slurm.mode, "auto")
        self.assertEqual(cfg.slurm.array_limit, 3)
        self.assertTrue(cfg.slurm.plan_dir.endswith("/plans/example"))
        self.assertTrue(cfg.slurm.workdir.endswith("/minimum_atomworks"))
        self.assertTrue(cfg.slurm.python_bin.endswith("/miniconda3/envs/atw_pp/bin/python"))
        self.assertTrue(cfg.slurm.log_dir.endswith("/logs/minimum_atw"))
        self.assertEqual(cfg.slurm.sbatch_common_args, ["--account=my_lab", "--qos=normal"])
        self.assertEqual(cfg.slurm.sbatch_gpu_args, ["--partition=gpu"])
        self.assertNotIn("slurm", cfg.merge_compatibility())

        with self.assertRaises(ValueError):
            Config(input_dir="/tmp/in", out_dir="/tmp/out", slurm={"chunk_size": 0})

        with self.assertRaises(ValueError):
            Config(input_dir="/tmp/in", out_dir="/tmp/out", slurm={"mode": "parallel"})

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

    def test_prepare_and_plugin_superimpose_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ValueError):
            Config(
                input_dir="/tmp/in",
                out_dir="/tmp/out",
                manipulations=[{"name": "superimpose_to_reference", "grain": "pdb"}],
                plugins=["superimpose_homology"],
            )

    def test_prepare_superimpose_forces_prepared_structure_persistence(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            manipulations=[{"name": "superimpose_to_reference", "grain": "pdb"}],
            keep_prepared_structures=False,
        )
        self.assertTrue(cfg.keep_prepared_structures)


if __name__ == "__main__":
    unittest.main()
