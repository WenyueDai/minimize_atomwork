from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from minimum_atw.core.tables import (
    BufferedTableWriter,
    PDB_KEY_COLS,
    STATUS_COLS,
    merge_pdb_frames_bulk,
    merge_pdb_frames,
    normalize_pdb_frame,
    read_frame,
    read_pdb_table,
    rows_to_pdb_frame,
    stack_pdb_frames,
    table_parts_dir,
)


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

    def test_merge_keeps_all_distinct_prefixed_columns(self) -> None:
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
                    "sup__anchor_atoms": 42,
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
                }
            ]
        )

        merged = merge_pdb_frames(base, extra)

        self.assertIn("iface__contact_distance", merged.columns)
        self.assertIn("sup__anchor_atoms", merged.columns)
        self.assertIn("ifm__contact_distance", merged.columns)
        self.assertIn("ifm__cell_size", merged.columns)

    def test_stack_table_frames_rejects_duplicate_identity_rows(self) -> None:
        frames = [
            pd.DataFrame([{"path": "/tmp/example.pdb", "assembly_id": "1", "grain": "structure", "chain_id": "", "role": "", "pair": "", "role_left": "", "role_right": ""}]),
            pd.DataFrame([{"path": "/tmp/example.pdb", "assembly_id": "1", "grain": "structure", "chain_id": "", "role": "", "pair": "", "role_left": "", "role_right": ""}]),
        ]

        with self.assertRaises(ValueError):
            stack_pdb_frames(frames)

    def test_bulk_merge_matches_iterative_merge(self) -> None:
        base = rows_to_pdb_frame(
            [
                {
                    "path": "/tmp/example.pdb",
                    "assembly_id": "1",
                    "grain": "interface",
                    "pair": "binder__target",
                    "role_left": "binder",
                    "role_right": "target",
                    "iface__contact_distance": 5.0,
                }
            ]
        )
        extra_one = rows_to_pdb_frame(
            [
                {
                    "path": "/tmp/example.pdb",
                    "assembly_id": "1",
                    "grain": "interface",
                    "pair": "binder__target",
                    "role_left": "binder",
                    "role_right": "target",
                    "ifm__contact_distance": 5.0,
                    "ifm__left_n_interface_residues": 4,
                }
            ]
        )
        extra_two = rows_to_pdb_frame(
            [
                {
                    "path": "/tmp/example.pdb",
                    "assembly_id": "1",
                    "grain": "interface",
                    "pair": "binder__target",
                    "role_left": "binder",
                    "role_right": "target",
                    "abcdr__chain_ids": "A",
                    "abseq__chain_ids": "A",
                }
            ]
        )

        iterative = merge_pdb_frames(merge_pdb_frames(base, extra_one), extra_two)
        bulk = merge_pdb_frames_bulk(base, [extra_one, extra_two])

        pd.testing.assert_frame_equal(iterative, bulk)

    def test_buffered_writer_reads_fragmented_generic_table_before_materialize(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_tables_") as tmp_dir:
            path = Path(tmp_dir) / "plugin_status.parquet"
            writer = BufferedTableWriter(path, flush_interval=2, columns=STATUS_COLS)

            writer.append_rows(
                [
                    {
                        "path": "/tmp/a.pdb",
                        "assembly_id": "1",
                        "plugin": "identity",
                        "status": "ok",
                        "message": "rows=1",
                    },
                    {
                        "path": "/tmp/b.pdb",
                        "assembly_id": "1",
                        "plugin": "identity",
                        "status": "ok",
                        "message": "rows=1",
                    },
                ]
            )

            self.assertFalse(path.exists())
            self.assertTrue(table_parts_dir(path).exists())
            fragmented = read_frame(path, STATUS_COLS)
            self.assertEqual(len(fragmented), 2)

            writer.materialize()
            self.assertTrue(path.exists())
            self.assertFalse(table_parts_dir(path).exists())
            materialized = read_frame(path, STATUS_COLS)
            self.assertEqual(len(materialized), 2)

    def test_buffered_pdb_writer_preserves_duplicate_identity_detection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_tables_") as tmp_dir:
            path = Path(tmp_dir) / "pdb.parquet"
            writer = BufferedTableWriter(path, flush_interval=1, normalize_frame=normalize_pdb_frame)

            writer.append_rows(
                [
                    {
                        "path": "/tmp/example.pdb",
                        "assembly_id": "1",
                        "grain": "structure",
                        "chain_id": "",
                        "role": "",
                        "pair": "",
                        "role_left": "",
                        "role_right": "",
                        "metric": 1,
                    }
                ]
            )
            writer.append_rows(
                [
                    {
                        "path": "/tmp/example.pdb",
                        "assembly_id": "1",
                        "grain": "structure",
                        "chain_id": "",
                        "role": "",
                        "pair": "",
                        "role_left": "",
                        "role_right": "",
                        "metric": 2,
                    }
                ]
            )

            frame = writer.materialize()
            self.assertEqual(len(frame), 2)
            with self.assertRaises(ValueError):
                merge_pdb_frames(pd.DataFrame(columns=PDB_KEY_COLS), read_pdb_table(path))


if __name__ == "__main__":
    unittest.main()
