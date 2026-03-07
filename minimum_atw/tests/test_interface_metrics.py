from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    from biotite.structure.io import load_structure
    from minimum_atw.plugins.interface_analysis.interface_metrics import (
        chain_residue_entries,
        interface_contact_summary,
        interface_residue_contact_pairs,
        residue_tokens,
        summarize_residue_properties,
    )
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "numpy"}:
        raise
    load_structure = None


@unittest.skipIf(load_structure is None, "interface metric dependencies are not installed")
class InterfaceMetricsTests(unittest.TestCase):
    def test_chain_residue_entries_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_iface_metrics_") as tmp_dir:
            path = Path(tmp_dir) / "toy.pdb"
            path.write_text(
                textwrap.dedent(
                    """\
                    ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                    ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                    ATOM      3  N   TYR A   2       3.000   0.000   0.000  1.00 20.00           N
                    TER
                    END
                    """
                )
            )
            arr = load_structure(path)

        entries = chain_residue_entries(arr)
        self.assertEqual(entries, [("A", 1, "G"), ("A", 2, "Y")])
        self.assertEqual(residue_tokens(entries), "A:1:G;A:2:Y")

    def test_interface_contact_summary_returns_contacted_atoms_and_residues(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_iface_metrics_") as tmp_dir:
            path = Path(tmp_dir) / "toy.pdb"
            path.write_text(
                textwrap.dedent(
                    """\
                    ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                    ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                    ATOM      3  N   ALA B   2       0.000   0.000   3.000  1.00 20.00           N
                    ATOM      4  CA  ALA B   2       1.200   0.000   3.000  1.00 20.00           C
                    ATOM      5  N   TYR C   4      50.000   0.000   0.000  1.00 20.00           N
                    TER
                    END
                    """
                )
            )
            arr = load_structure(path)

        left = arr[arr.chain_id.astype(str) == "A"]
        right = arr[arr.chain_id.astype(str) == "B"]
        far = arr[arr.chain_id.astype(str) == "C"]

        summary = interface_contact_summary(left, right, contact_distance=5.0)
        none_summary = interface_contact_summary(left, far, contact_distance=5.0)

        self.assertIsNotNone(summary)
        self.assertIsNone(none_summary)
        assert summary is not None
        self.assertEqual(summary["n_contact_atom_pairs"], 4)
        self.assertEqual(summary["left_interface_residues"], [("A", 1, "G")])
        self.assertEqual(summary["right_interface_residues"], [("B", 2, "A")])

    def test_residue_contact_pairs_and_property_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_iface_metrics_") as tmp_dir:
            path = Path(tmp_dir) / "toy.pdb"
            path.write_text(
                textwrap.dedent(
                    """\
                    ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
                    ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
                    ATOM      3  N   ASP B   2       0.000   0.000   3.000  1.00 20.00           N
                    ATOM      4  CA  ASP B   2       1.200   0.000   3.000  1.00 20.00           C
                    TER
                    END
                    """
                )
            )
            arr = load_structure(path)

        left = arr[arr.chain_id.astype(str) == "A"]
        right = arr[arr.chain_id.astype(str) == "B"]
        pair_list, _left_contact, right_contact = interface_residue_contact_pairs(
            left,
            right,
            contact_cutoff=5.0,
            cell_size=5.0,
        )

        self.assertEqual(pair_list, [(("A", 1, "G"), ("B", 2, "D"))])
        self.assertEqual(
            summarize_residue_properties(
                [{"chain_id": "B", "res_id": 2, "res_name": "ASP", "atoms": right_contact, "aa": "D"}],
                "right",
            ),
            {
                "right_n_interface_residues": 1,
                "right_interface_charge_sum": -1,
                "right_interface_hydrophobic_fraction": 0.0,
                "right_interface_polar_fraction": 0.0,
                "right_interface_aromatic_fraction": 0.0,
                "right_interface_glycine_fraction": 0.0,
                "right_interface_proline_fraction": 0.0,
            },
        )


if __name__ == "__main__":
    unittest.main()
