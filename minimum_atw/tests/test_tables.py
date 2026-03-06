from __future__ import annotations

import unittest

import pandas as pd

from minimum_atw.core.tables import merge_table_frames, rows_to_frame, stack_table_frames


class TableTests(unittest.TestCase):
    def test_rows_to_frame_orders_identity_columns_first(self) -> None:
        frame = rows_to_frame(
            [{"metric": 3, "assembly_id": "1", "path": "/tmp/example.pdb"}],
            "structures",
        )

        self.assertEqual(list(frame.columns), ["path", "assembly_id", "metric"])

    def test_merge_table_frames_rejects_overlapping_columns(self) -> None:
        base = pd.DataFrame([{"path": "/tmp/example.pdb", "assembly_id": "1", "metric": 1}])
        extra = pd.DataFrame([{"path": "/tmp/example.pdb", "assembly_id": "1", "metric": 2}])

        with self.assertRaises(ValueError):
            merge_table_frames(base, extra, "structures")

    def test_stack_table_frames_rejects_duplicate_identity_rows(self) -> None:
        frames = [
            pd.DataFrame([{"path": "/tmp/example.pdb", "assembly_id": "1"}]),
            pd.DataFrame([{"path": "/tmp/example.pdb", "assembly_id": "1"}]),
        ]

        with self.assertRaises(ValueError):
            stack_table_frames(frames, "structures")


if __name__ == "__main__":
    unittest.main()
