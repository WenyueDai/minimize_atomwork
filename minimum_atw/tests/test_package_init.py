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


if __name__ == "__main__":
    unittest.main()
