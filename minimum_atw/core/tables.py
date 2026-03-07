from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


TABLE_SUFFIX = ".parquet"
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
]
IDENTITY_COLS = set(PDB_KEY_COLS)
STATUS_COLS = ["path", "assembly_id", "plugin", "status", "message"]
BAD_COLS = ["path", "error"]
MANIFEST_COLS = ["path", "prepared_path"]


def normalize_grain(value: Any) -> str:
    normalized = str(value or "structure").strip().lower()
    if normalized not in PDB_GRAINS:
        raise ValueError(f"Unknown grain '{value}'. Expected one of: {', '.join(PDB_GRAINS)}")
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
    df = pd.DataFrame(rows)
    for key in PDB_KEY_COLS:
        if key not in df.columns:
            df[key] = ""
        else:
            df[key] = df[key].fillna("")
    df["grain"] = df["grain"].map(normalize_grain)
    ordered = [col for col in PDB_KEY_COLS if col in df.columns]
    ordered.extend(col for col in df.columns if col not in ordered)
    return sort_pdb_frame(df.loc[:, ordered])


def read_frame(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    return pd.read_parquet(path)


def read_pdb_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return empty_pdb_frame()
    frame = pd.read_parquet(path)
    for key in PDB_KEY_COLS:
        if key not in frame.columns:
            frame[key] = ""
        else:
            frame[key] = frame[key].fillna("")
    if "grain" in frame.columns:
        frame["grain"] = frame["grain"].map(normalize_grain)
    return sort_pdb_frame(frame)


def merge_pdb_frames(base: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    keys = PDB_KEY_COLS
    if base.empty:
        base = empty_pdb_frame()
    if extra.empty:
        return sort_pdb_frame(base)

    missing = [col for col in keys if col not in extra.columns]
    if missing:
        raise ValueError(f"Missing merge keys for pdb: {', '.join(missing)}")

    extra = extra.loc[:, list(dict.fromkeys([*keys, *[col for col in extra.columns if col not in keys]]))]

    if extra.duplicated(keys).any():
        raise ValueError("Duplicate identity rows detected in pdb")
    if not base.empty and base.duplicated(keys).any():
        raise ValueError("Duplicate base identity rows detected in pdb")

    non_key_cols = [col for col in extra.columns if col not in keys]
    if not non_key_cols:
        return sort_pdb_frame(base)

    overlapping = [col for col in non_key_cols if col in base.columns]
    if overlapping:
        raise ValueError(f"Overlapping output columns detected in pdb: {', '.join(sorted(overlapping))}")

    if base.empty:
        return sort_pdb_frame(extra.loc[:, [*keys, *non_key_cols]].copy())

    merged = base.merge(extra.loc[:, [*keys, *non_key_cols]], on=keys, how="left", validate="one_to_one")
    return sort_pdb_frame(merged)


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
    frame.to_parquet(dir_path / (filename or f"{PDB_TABLE_NAME}{TABLE_SUFFIX}"), index=False)


def write_frame(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    pd.DataFrame(rows, columns=columns).to_parquet(path, index=False)


def append_rows(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows, columns=columns) if columns else pd.DataFrame(rows)
    if path.exists():
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True, sort=False).drop_duplicates()
    df.to_parquet(path, index=False)


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
