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

    def test_stack_table_frames_rejects_duplicate_identity_rows(self) -> None:
        frames = [
            pd.DataFrame([{"path": "/tmp/example.pdb", "assembly_id": "1", "grain": "structure", "chain_id": "", "role": "", "pair": "", "role_left": "", "role_right": ""}]),
            pd.DataFrame([{"path": "/tmp/example.pdb", "assembly_id": "1", "grain": "structure", "chain_id": "", "role": "", "pair": "", "role_left": "", "role_right": ""}]),
        ]

        with self.assertRaises(ValueError):
            stack_pdb_frames(frames)


if __name__ == "__main__":
    unittest.main()
