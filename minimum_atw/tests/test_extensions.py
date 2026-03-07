from __future__ import annotations

import unittest

from minimum_atw.core.extensions import extension_catalog


class ExtensionCatalogTests(unittest.TestCase):
    def test_extensions_are_separated_by_scope_and_function(self) -> None:
        catalog = extension_catalog()

        self.assertIn("pdb_quality_control", catalog)
        self.assertIn("pdb_manipulation", catalog)
        self.assertIn("pdb_calculation", catalog)
        self.assertIn("dataset_quality_control", catalog)
        self.assertIn("dataset_manipulation", catalog)
        self.assertIn("dataset_calculation", catalog)

        self.assertEqual([item.name for item in catalog["pdb_quality_control"]], ["chain_continuity", "structure_clashes"])
        self.assertEqual([item.name for item in catalog["pdb_manipulation"]], ["center_on_origin"])
        self.assertEqual(catalog["dataset_quality_control"], [])
        self.assertEqual([item.name for item in catalog["dataset_manipulation"]], ["superimpose_homology"])
        self.assertEqual(
            [item.name for item in catalog["pdb_calculation"]],
            [
                "abepitope_score",
                "antibody_cdr_lengths",
                "antibody_cdr_sequences",
                "chain_stats",
                "identity",
                "interface_contacts",
                "interface_metrics",
                "role_sequences",
                "role_stats",
                "rosetta_interface_example",
            ],
        )
        self.assertEqual(
            [item.name for item in catalog["dataset_calculation"]],
            ["cdr_entropy", "cluster", "dataset_annotations", "interface_summary"],
        )


if __name__ == "__main__":
    unittest.main()
