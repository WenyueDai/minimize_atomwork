from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

import pandas as pd


TABLE_SUFFIX = ".parquet"
TABLE_PARTS_SUFFIX = ".parts"
PDB_TABLE_NAME = "pdb"
PDB_GRAINS = ("structure", "chain", "role", "interface")
PDB_KEY_COLS = [
    "path",
    "assembly_id",
    "grain",
    "chain_id",
    "role",
    "pair",
    "role_left",
    "role_right",
    "sub_id",  # catch-all sub-identity for custom grains (residue, domain, site, …)
]
IDENTITY_COLS = set(PDB_KEY_COLS)
STATUS_COLS = ["path", "assembly_id", "plugin", "status", "message"]
BAD_COLS = ["path", "error"]
MANIFEST_COLS = [
    "path",
    "prepared_path",
    "source_name",
    "source_format",
    "source_size_bytes",
    "source_mtime_ns",
    "loaded_path",
    "loaded_format",
    "n_atoms_loaded",
    "n_chains_loaded",
]

def normalize_grain(value: Any) -> str:
    normalized = str(value or "structure").strip().lower()
    if not normalized:
        return "structure"
    return normalized


def prefix_row(row: dict[str, Any], prefix: str, *, default_grain: str = "structure") -> dict[str, Any]:
    out = {key: "" for key in PDB_KEY_COLS}
    out["grain"] = normalize_grain(row.get("grain", default_grain))
    for key, value in row.items():
        if key == "grain":
            out["grain"] = normalize_grain(value)
        elif key in IDENTITY_COLS:
            out[key] = value if value is not None else ""
        else:
            out[f"{prefix}__{key}"] = value
    return out


def empty_pdb_rows() -> list[dict[str, Any]]:
    return []


def empty_pdb_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=PDB_KEY_COLS)


def normalize_pdb_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return empty_pdb_frame()
    df = frame.copy()
    for key in PDB_KEY_COLS:
        if key not in df.columns:
            df[key] = ""
        else:
            df[key] = df[key].fillna("")
    df["grain"] = df["grain"].map(normalize_grain)
    ordered = [col for col in PDB_KEY_COLS if col in df.columns]
    ordered.extend(col for col in df.columns if col not in ordered)
    return sort_pdb_frame(df.loc[:, ordered])


def sort_pdb_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    sort_cols = [col for col in PDB_KEY_COLS if col in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, kind="stable")
    return df.reset_index(drop=True)


def rows_to_pdb_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return empty_pdb_frame()
    return normalize_pdb_frame(pd.DataFrame(rows))


def table_parts_dir(path: Path) -> Path:
    return path.parent / f"{path.name}{TABLE_PARTS_SUFFIX}"


def clear_table_artifacts(path: Path) -> None:
    if path.exists():
        path.unlink()
    parts_dir = table_parts_dir(path)
    if parts_dir.exists():
        shutil.rmtree(parts_dir)


def _table_part_paths(path: Path) -> list[Path]:
    parts_dir = table_parts_dir(path)
    if not parts_dir.exists():
        return []
    return sorted(part for part in parts_dir.glob(f"*{TABLE_SUFFIX}") if part.is_file())


def _read_fragmented_parquet(
    path: Path,
    *,
    empty_frame: pd.DataFrame,
    dedupe_subset: list[str] | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if path.exists():
        frames.append(pd.read_parquet(path))
    for part in _table_part_paths(path):
        frames.append(pd.read_parquet(part))
    if not frames:
        return empty_frame.copy()
    combined = pd.concat(frames, ignore_index=True, sort=False)
    if dedupe_subset is None:
        combined = combined.drop_duplicates()
    else:
        combined = combined.drop_duplicates(subset=dedupe_subset)
    return combined.reset_index(drop=True)


def read_frame(path: Path, columns: list[str]) -> pd.DataFrame:
    frame = _read_fragmented_parquet(path, empty_frame=pd.DataFrame(columns=columns))
    for column in columns:
        if column not in frame.columns:
            frame[column] = pd.Series(dtype="object")
    ordered = [column for column in columns if column in frame.columns]
    ordered.extend(column for column in frame.columns if column not in ordered)
    return frame.loc[:, ordered]


def read_pdb_table(path: Path) -> pd.DataFrame:
    frame = _read_fragmented_parquet(path, empty_frame=empty_pdb_frame())
    return normalize_pdb_frame(frame)


def _prepare_pdb_merge_frame(frame: pd.DataFrame) -> pd.DataFrame:
    keys = PDB_KEY_COLS
    if frame.empty:
        return empty_pdb_frame()
    prepared = frame.copy()
    for key in keys:
        if key not in prepared.columns:
            prepared[key] = ""
        else:
            prepared[key] = prepared[key].fillna("")
    if "grain" in prepared.columns:
        prepared["grain"] = prepared["grain"].map(normalize_grain)
    return prepared.loc[:, list(dict.fromkeys([*keys, *[col for col in prepared.columns if col not in keys]]))]


def merge_pdb_frames_bulk(base: pd.DataFrame, extras: list[pd.DataFrame]) -> pd.DataFrame:
    keys = PDB_KEY_COLS
    prepared_base = _prepare_pdb_merge_frame(base)
    prepared_extras: list[pd.DataFrame] = []

    if not prepared_base.empty and prepared_base.duplicated(keys).any():
        raise ValueError("Duplicate base identity rows detected in pdb")

    seen_non_key_cols = {col for col in prepared_base.columns if col not in keys}
    for extra in extras:
        prepared_extra = _prepare_pdb_merge_frame(extra)
        if prepared_extra.empty:
            continue
        if prepared_extra.duplicated(keys).any():
            raise ValueError("Duplicate identity rows detected in pdb")
        non_key_cols = [col for col in prepared_extra.columns if col not in keys]
        if not non_key_cols:
            continue
        overlapping = [col for col in non_key_cols if col in seen_non_key_cols]
        if overlapping:
            raise ValueError(f"Overlapping output columns detected in pdb: {', '.join(sorted(overlapping))}")
        seen_non_key_cols.update(non_key_cols)
        prepared_extras.append(prepared_extra.loc[:, [*keys, *non_key_cols]].copy())

    if not prepared_extras:
        return sort_pdb_frame(prepared_base)

    if prepared_base.empty:
        merged = prepared_extras[0].set_index(keys)
        remaining = prepared_extras[1:]
    else:
        merged = prepared_base.set_index(keys)
        remaining = prepared_extras

    for prepared_extra in remaining:
        merged = merged.join(prepared_extra.set_index(keys), how="left")

    return sort_pdb_frame(merged.reset_index())


def merge_pdb_frames(base: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    keys = PDB_KEY_COLS
    if base.empty:
        base = empty_pdb_frame()
    if extra.empty:
        return sort_pdb_frame(base)
    return merge_pdb_frames_bulk(base, [extra])


def stack_pdb_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return empty_pdb_frame()

    combined = pd.concat(non_empty, ignore_index=True, sort=False)
    missing = [col for col in PDB_KEY_COLS if col not in combined.columns]
    if missing:
        raise ValueError(f"Missing identity columns for pdb: {', '.join(missing)}")
    if combined.duplicated(PDB_KEY_COLS).any():
        raise ValueError("Duplicate identity rows detected across datasets in pdb")
    return sort_pdb_frame(combined)


def write_pdb_table(
    dir_path: Path,
    frame: pd.DataFrame,
    *,
    skip_empty: bool = False,
    filename: str | None = None,
) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    if skip_empty and frame.empty:
        return
    path = dir_path / (filename or f"{PDB_TABLE_NAME}{TABLE_SUFFIX}")
    frame.to_parquet(path, index=False)
    parts_dir = table_parts_dir(path)
    if parts_dir.exists():
        shutil.rmtree(parts_dir)


def write_frame(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    pd.DataFrame(rows, columns=columns).to_parquet(path, index=False)
    parts_dir = table_parts_dir(path)
    if parts_dir.exists():
        shutil.rmtree(parts_dir)


def _write_table_part(path: Path, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    parts_dir = table_parts_dir(path)
    parts_dir.mkdir(parents=True, exist_ok=True)
    part_path = parts_dir / f"part-{uuid4().hex}{TABLE_SUFFIX}"
    frame.to_parquet(part_path, index=False)


class BufferedTableWriter:
    def __init__(
        self,
        path: Path,
        *,
        flush_interval: int,
        columns: list[str] | None = None,
        dedupe_subset: list[str] | None = None,
        normalize_frame: Any | None = None,
    ) -> None:
        self.path = path
        self.flush_interval = max(int(flush_interval), 1)
        self.columns = list(columns) if columns else None
        self.dedupe_subset = list(dedupe_subset) if dedupe_subset else None
        self.normalize_frame = normalize_frame
        self._pending_frames: list[pd.DataFrame] = []
        self._pending_rows = 0

    def append_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        frame = pd.DataFrame(rows, columns=self.columns) if self.columns else pd.DataFrame(rows)
        self.append_frame(frame)

    def append_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        self._pending_frames.append(frame.copy())
        self._pending_rows += len(frame)
        if self._pending_rows >= self.flush_interval:
            self.flush()

    def flush(self) -> None:
        if not self._pending_frames:
            return
        frame = pd.concat(self._pending_frames, ignore_index=True, sort=False)
        self._pending_frames = []
        self._pending_rows = 0
        frame = self._normalize(frame)
        _write_table_part(self.path, frame)

    def read(self) -> pd.DataFrame:
        self.flush()
        empty_frame = pd.DataFrame(columns=self.columns) if self.columns else pd.DataFrame()
        frame = _read_fragmented_parquet(
            self.path,
            empty_frame=empty_frame,
            dedupe_subset=self.dedupe_subset,
        )
        return self._normalize(frame)

    def materialize(self, *, skip_empty: bool = False) -> pd.DataFrame:
        frame = self.read()
        if frame.empty and skip_empty:
            clear_table_artifacts(self.path)
            return frame
        self.path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(self.path, index=False)
        parts_dir = table_parts_dir(self.path)
        if parts_dir.exists():
            shutil.rmtree(parts_dir)
        return frame

    def _normalize(self, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        if self.columns:
            for column in self.columns:
                if column not in out.columns:
                    out[column] = pd.NA
            ordered = [column for column in self.columns if column in out.columns]
            ordered.extend(column for column in out.columns if column not in ordered)
            out = out.loc[:, ordered]
        if self.normalize_frame is not None:
            out = self.normalize_frame(out)
        elif self.dedupe_subset is None:
            out = out.drop_duplicates().reset_index(drop=True)
        elif not out.empty:
            out = out.drop_duplicates(subset=self.dedupe_subset).reset_index(drop=True)
        return out


def append_rows(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    writer = BufferedTableWriter(path, flush_interval=max(len(rows), 1), columns=columns)
    writer.append_rows(rows)
    writer.materialize()


def count_pdb_rows(frame: pd.DataFrame) -> dict[str, int]:
    counts = {PDB_TABLE_NAME: len(frame)}
    if frame.empty or "grain" not in frame.columns:
        counts.update(structures=0, chains=0, roles=0, interfaces=0)
        return counts
    grain_counts = frame["grain"].astype(str).value_counts().to_dict()
    counts["structures"] = int(grain_counts.get("structure", 0))
    counts["chains"] = int(grain_counts.get("chain", 0))
    counts["roles"] = int(grain_counts.get("role", 0))
    counts["interfaces"] = int(grain_counts.get("interface", 0))
    return counts
