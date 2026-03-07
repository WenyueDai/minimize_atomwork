from __future__ import annotations

import unittest

from minimum_atw.runtime.stage_buffer import FrameBuffer, TableBuffer


class StageBufferTests(unittest.TestCase):
    def test_table_buffer_spills_and_reassembles_rows(self) -> None:
        buffer = TableBuffer(row_limit=1)
        try:
            buffer.add({"path": "/tmp/a.pdb", "assembly_id": "1", "grain": "structure", "metric": 1})
            buffer.add({"path": "/tmp/b.pdb", "assembly_id": "1", "grain": "structure", "metric": 2})
            frame = buffer.finalize()
        finally:
            buffer.close()

        self.assertEqual(len(frame), 2)
        self.assertEqual(frame["metric"].tolist(), [1, 2])

    def test_frame_buffer_spills_and_deduplicates_rows(self) -> None:
        buffer = FrameBuffer(columns=["path", "error"], row_limit=1)
        try:
            buffer.add({"path": "/tmp/a.pdb", "error": "bad"})
            buffer.add({"path": "/tmp/a.pdb", "error": "bad"})
            frame = buffer.finalize(deduplicate=True)
        finally:
            buffer.close()

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["path"], "/tmp/a.pdb")


if __name__ == "__main__":
    unittest.main()
