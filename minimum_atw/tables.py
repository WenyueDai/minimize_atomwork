from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


TABLE_NAMES = ("structures", "chains", "roles", "interfaces")
TABLE_SUFFIX = ".parquet"

IDENTITY_COLS = {
    "path",
    "assembly_id",
    "chain_id",
    "role",
    "pair",
    "role_left",
    "role_right",
}

KEY_COLS = {
    "structures": ["path", "assembly_id"],
    "chains": ["path", "assembly_id", "chain_id"],
    "roles": ["path", "assembly_id", "role"],
    "interfaces": ["path", "assembly_id", "pair", "role_left", "role_right"],
}

STATUS_COLS = ["path", "assembly_id", "plugin", "status", "message"]
BAD_COLS = ["path", "error"]
MANIFEST_COLS = ["path", "prepared_path"]


class TableOps:
    @staticmethod
    def empty_frame(table_name: str) -> pd.DataFrame:
        return pd.DataFrame(columns=KEY_COLS[table_name])

    @staticmethod
    def sort_frame(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
        if df.empty:
            return df
        sort_cols = [col for col in KEY_COLS[table_name] if col in df.columns]
        if sort_cols:
            df = df.sort_values(sort_cols, kind="stable")
        return df.reset_index(drop=True)

    @staticmethod
    def from_rows(rows: list[dict[str, Any]], table_name: str) -> pd.DataFrame:
        if not rows:
            return TableOps.empty_frame(table_name)
        df = pd.DataFrame(rows)
        ordered = [col for col in KEY_COLS[table_name] if col in df.columns]
        ordered.extend(col for col in df.columns if col not in ordered)
        return TableOps.sort_frame(df.loc[:, ordered], table_name)

    @staticmethod
    def read_frame(path: Path, columns: list[str]) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame(columns=columns)
        return pd.read_parquet(path)

    @staticmethod
    def read_table(path: Path, table_name: str) -> pd.DataFrame:
        if not path.exists():
            return TableOps.empty_frame(table_name)
        return TableOps.sort_frame(pd.read_parquet(path), table_name)

    @staticmethod
    def merge_frames(base: pd.DataFrame, extra: pd.DataFrame, table_name: str) -> pd.DataFrame:
        keys = KEY_COLS[table_name]
        if base.empty:
            base = TableOps.empty_frame(table_name)
        if extra.empty:
            return TableOps.sort_frame(base, table_name)

        missing = [col for col in keys if col not in extra.columns]
        if missing:
            raise ValueError(f"Missing merge keys for {table_name}: {', '.join(missing)}")

        extra = extra.loc[:, list(dict.fromkeys([*keys, *[col for col in extra.columns if col not in keys]]))]

        if extra.duplicated(keys).any():
            raise ValueError(f"Duplicate identity rows detected in {table_name}")
        if not base.empty and base.duplicated(keys).any():
            raise ValueError(f"Duplicate base identity rows detected in {table_name}")

        non_key_cols = [col for col in extra.columns if col not in keys]
        if not non_key_cols:
            return TableOps.sort_frame(base, table_name)

        overlapping = [col for col in non_key_cols if col in base.columns]
        if overlapping:
            raise ValueError(f"Overlapping output columns detected in {table_name}: {', '.join(sorted(overlapping))}")

        if base.empty:
            return TableOps.sort_frame(extra.loc[:, [*keys, *non_key_cols]].copy(), table_name)

        merged = base.merge(extra.loc[:, [*keys, *non_key_cols]], on=keys, how="left", validate="one_to_one")
        return TableOps.sort_frame(merged, table_name)

    @staticmethod
    def write_tables(dir_path: Path, tables: dict[str, pd.DataFrame]) -> None:
        dir_path.mkdir(parents=True, exist_ok=True)
        for table_name in TABLE_NAMES:
            tables[table_name].to_parquet(dir_path / f"{table_name}{TABLE_SUFFIX}", index=False)

    @staticmethod
    def write_frame(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
        pd.DataFrame(rows, columns=columns).to_parquet(path, index=False)


def prefix_row(row: dict[str, Any], prefix: str) -> dict[str, Any]:
    out = {}
    for key, value in row.items():
        if key == "__table__":
            continue
        if key in IDENTITY_COLS:
            out[key] = value
        else:
            out[f"{prefix}__{key}"] = value
    return out


def empty_tables() -> dict[str, list[dict[str, Any]]]:
    return {table_name: [] for table_name in TABLE_NAMES}


def empty_frame(table_name: str) -> pd.DataFrame:
    return TableOps.empty_frame(table_name)


def sort_frame(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    return TableOps.sort_frame(df, table_name)


def rows_to_frame(rows: list[dict[str, Any]], table_name: str) -> pd.DataFrame:
    return TableOps.from_rows(rows, table_name)


def read_frame(path: Path, columns: list[str]) -> pd.DataFrame:
    return TableOps.read_frame(path, columns)


def read_table(path: Path, table_name: str) -> pd.DataFrame:
    return TableOps.read_table(path, table_name)


def merge_table_frames(base: pd.DataFrame, extra: pd.DataFrame, table_name: str) -> pd.DataFrame:
    return TableOps.merge_frames(base, extra, table_name)


def stack_table_frames(frames: list[pd.DataFrame], table_name: str) -> pd.DataFrame:
    keys = KEY_COLS[table_name]
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return empty_frame(table_name)

    combined = pd.concat(non_empty, ignore_index=True, sort=False)
    missing = [col for col in keys if col not in combined.columns]
    if missing:
        raise ValueError(f"Missing identity columns for {table_name}: {', '.join(missing)}")
    if combined.duplicated(keys).any():
        raise ValueError(f"Duplicate identity rows detected across datasets in {table_name}")
    return sort_frame(combined, table_name)


def write_tables(dir_path: Path, tables: dict[str, pd.DataFrame]) -> None:
    TableOps.write_tables(dir_path, tables)


def write_frame(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    TableOps.write_frame(path, rows, columns)
