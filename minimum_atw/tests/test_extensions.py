from __future__ import annotations

import unittest

from minimum_atw.core.extensions import EXTENSION_CLASSES, extension_catalog


class ExtensionCatalogTests(unittest.TestCase):
    def test_extension_class_metadata_is_public(self) -> None:
        self.assertEqual(EXTENSION_CLASSES["pdb_prepare"].display_name, "PDB Prepare Plugins")
        self.assertEqual(EXTENSION_CLASSES["pdb_calculation"].stage, "run-plugin")
        self.assertEqual(EXTENSION_CLASSES["dataset_calculation"].config_key, "dataset_analyses")

    def test_extensions_are_separated_by_scope_and_function(self) -> None:
        catalog = extension_catalog()

        self.assertIn("pdb_prepare", catalog)
        self.assertIn("pdb_calculation", catalog)
        self.assertIn("dataset_calculation", catalog)

        self.assertEqual(
            [item.name for item in catalog["pdb_prepare"]],
            ["center_on_origin", "chain_continuity", "rosetta_preprocess", "structure_clashes", "superimpose_to_reference"],
        )
        self.assertEqual(
            [item.name for item in catalog["pdb_calculation"]],
            [
                "abepitope_score",
                "ablang2_score",
                "antibody_cdr_sequences",
                "chain_stats",
                "dockq_score",
                "esm_if1_score",
                "identity",
                "interface_contacts",
                "interface_metrics",
                "pdockq_score",
                "role_sequences",
                "role_stats",
                "rosetta_interface_example",
                "structure_rmsd",
            ],
        )
        self.assertEqual(
            [item.name for item in catalog["dataset_calculation"]],
            ["cdr_entropy", "cluster", "dataset_annotations", "interface_summary"],
        )


if __name__ == "__main__":
    unittest.main()
