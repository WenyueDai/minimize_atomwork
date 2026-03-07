from __future__ import annotations

import unittest

import pandas as pd

from minimum_atw.core.tables import PDB_KEY_COLS, merge_pdb_frames, rows_to_pdb_frame, stack_pdb_frames


class TableTests(unittest.TestCase):
    def test_rows_to_frame_orders_identity_columns_first(self) -> None:
        frame = rows_to_pdb_frame([{"metric": 3, "assembly_id": "1", "path": "/tmp/example.pdb", "grain": "structure"}])

        self.assertEqual(list(frame.columns), [*PDB_KEY_COLS, "metric"])

    def test_merge_table_frames_rejects_overlapping_columns(self) -> None:
        base = pd.DataFrame(
            [{"path": "/tmp/example.pdb", "assembly_id": "1", "grain": "structure", "chain_id": "", "role": "", "pair": "", "role_left": "", "role_right": "", "metric": 1}]
        )
        extra = pd.DataFrame(
            [{"path": "/tmp/example.pdb", "assembly_id": "1", "grain": "structure", "chain_id": "", "role": "", "pair": "", "role_left": "", "role_right": "", "metric": 2}]
        )

        with self.assertRaises(ValueError):
            merge_pdb_frames(base, extra)

    def test_merge_prunes_known_redundant_columns_when_values_match(self) -> None:
        base = pd.DataFrame(
            [
                {
                    "path": "/tmp/example.pdb",
                    "assembly_id": "1",
                    "grain": "interface",
                    "chain_id": "",
                    "role": "",
                    "pair": "binder__target",
                    "role_left": "binder",
                    "role_right": "target",
                    "iface__contact_distance": 5.0,
                    "iface__n_left_interface_residues": 4,
                    "iface__n_right_interface_residues": 6,
                    "abseq__chain_ids": "A",
                    "abseq__numbering_scheme": "imgt",
                    "abseq__cdr_definition": "imgt",
                    "abseq__sequence_length": 120,
                    "sup__anchor_atoms_fixed": 42,
                }
            ]
        )
        extra = pd.DataFrame(
            [
                {
                    "path": "/tmp/example.pdb",
                    "assembly_id": "1",
                    "grain": "interface",
                    "chain_id": "",
                    "role": "",
                    "pair": "binder__target",
                    "role_left": "binder",
                    "role_right": "target",
                    "ifm__contact_distance": 5.0,
                    "ifm__cell_size": 5.0,
                    "ifm__left_n_interface_residues": 4,
                    "ifm__right_n_interface_residues": 6,
                    "abcdr__chain_ids": "A",
                    "abcdr__numbering_scheme": "imgt",
                    "abcdr__cdr_definition": "imgt",
                    "abcdr__sequence_length": 120,
                    "sup__anchor_atoms_mobile": 42,
                }
            ]
        )

        merged = merge_pdb_frames(base, extra)

        self.assertIn("iface__contact_distance", merged.columns)
        self.assertIn("abseq__chain_ids", merged.columns)
        self.assertIn("sup__anchor_atoms_fixed", merged.columns)
        self.assertNotIn("ifm__contact_distance", merged.columns)
        self.assertNotIn("ifm__cell_size", merged.columns)
        self.assertNotIn("ifm__left_n_interface_residues", merged.columns)
        self.assertNotIn("ifm__right_n_interface_residues", merged.columns)
        self.assertNotIn("abcdr__chain_ids", merged.columns)
        self.assertNotIn("abcdr__numbering_scheme", merged.columns)
        self.assertNotIn("abcdr__cdr_definition", merged.columns)
        self.assertNotIn("abcdr__sequence_length", merged.columns)
        self.assertNotIn("sup__anchor_atoms_mobile", merged.columns)

    def test_stack_table_frames_rejects_duplicate_identity_rows(self) -> None:
        frames = [
            pd.DataFrame([{"path": "/tmp/example.pdb", "assembly_id": "1", "grain": "structure", "chain_id": "", "role": "", "pair": "", "role_left": "", "role_right": ""}]),
            pd.DataFrame([{"path": "/tmp/example.pdb", "assembly_id": "1", "grain": "structure", "chain_id": "", "role": "", "pair": "", "role_left": "", "role_right": ""}]),
        ]

        with self.assertRaises(ValueError):
            stack_pdb_frames(frames)


if __name__ == "__main__":
    unittest.main()
