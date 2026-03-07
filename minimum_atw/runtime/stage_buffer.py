from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from ..core.tables import (
    read_frame,
    read_pdb_table,
    rows_to_pdb_frame,
    stack_pdb_frames,
)


DEFAULT_ROW_LIMIT = 10_000


class TableBuffer:
    def __init__(self, *, row_limit: int = DEFAULT_ROW_LIMIT) -> None:
        self._row_limit = max(1, int(row_limit))
        self._pending: list[dict[str, Any]] = []
        self._spilled: list[Path] = []
        self._tmp_dir = tempfile.TemporaryDirectory(prefix="minimum_atw_table_buffer_")
        self._tmp_path = Path(self._tmp_dir.name)

    def add(self, row: dict[str, Any]) -> None:
        self._pending.append(row)
        if len(self._pending) >= self._row_limit:
            self._flush()

    def add_rows(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            self.add(row)

    def _flush(self) -> None:
        if not self._pending:
            return
        part_index = len(self._spilled)
        part_path = self._tmp_path / f"pdb_{part_index:04d}.parquet"
        rows_to_pdb_frame(self._pending).to_parquet(part_path, index=False)
        self._spilled.append(part_path)
        self._pending = []

    def finalize(self) -> pd.DataFrame:
        self._flush()
        spilled_frames = [read_pdb_table(path) for path in self._spilled]
        return stack_pdb_frames(spilled_frames)

    def close(self) -> None:
        self._tmp_dir.cleanup()


class FrameBuffer:
    def __init__(self, *, columns: list[str], row_limit: int = DEFAULT_ROW_LIMIT) -> None:
        self._columns = list(columns)
        self._row_limit = max(1, int(row_limit))
        self._pending: list[dict[str, Any]] = []
        self._spilled: list[Path] = []
        self._tmp_dir = tempfile.TemporaryDirectory(prefix="minimum_atw_frame_buffer_")
        self._tmp_path = Path(self._tmp_dir.name)

    def add(self, row: dict[str, Any]) -> None:
        self._pending.append(row)
        if len(self._pending) >= self._row_limit:
            self._flush()

    def _flush(self) -> None:
        if not self._pending:
            return
        part_index = len(self._spilled)
        part_path = self._tmp_path / f"rows_{part_index:04d}.parquet"
        pd.DataFrame(self._pending, columns=self._columns).to_parquet(part_path, index=False)
        self._spilled.append(part_path)
        self._pending = []

    def finalize(self, *, deduplicate: bool = False) -> pd.DataFrame:
        self._flush()
        frames = [read_frame(path, self._columns) for path in self._spilled]
        if not frames:
            return pd.DataFrame(columns=self._columns)
        combined = pd.concat(frames, ignore_index=True, sort=False)
        if deduplicate:
            combined = combined.drop_duplicates()
        return combined.reset_index(drop=True)

    def close(self) -> None:
        self._tmp_dir.cleanup()
