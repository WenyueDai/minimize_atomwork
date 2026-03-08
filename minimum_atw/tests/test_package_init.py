from __future__ import annotations

import unittest


class PackageInitTests(unittest.TestCase):
    def test_public_api_is_declared_without_eager_pipeline_import(self) -> None:
        import minimum_atw

        self.assertIn("run_pipeline", minimum_atw.__all__)
        self.assertIn("analyze_dataset_outputs", minimum_atw.__all__)
        self.assertIn("submit_slurm_plan", minimum_atw.__all__)
        self.assertIn("submit_slurm_chunked_pipeline", minimum_atw.__all__)

    def test_unknown_attribute_raises_attribute_error(self) -> None:
        import minimum_atw

        with self.assertRaises(AttributeError):
            minimum_atw.__getattr__("missing_name")

    def test_cli_parser_imports_and_exposes_list_extensions(self) -> None:
        from minimum_atw import cli

        parser = cli._build_parser()
        args = parser.parse_args(["list-extensions"])
        self.assertEqual(args.command, "list-extensions")

    def test_cli_parser_accepts_minimal_submit_slurm_invocation(self) -> None:
        from minimum_atw import cli

        parser = cli._build_parser()
        args = parser.parse_args(["submit-slurm", "--config", "example.yaml"])
        self.assertEqual(args.command, "submit-slurm")
        self.assertEqual(args.config, "example.yaml")
        self.assertIsNone(args.chunk_size)
        self.assertIsNone(args.plan_dir)


if __name__ == "__main__":
    unittest.main()
