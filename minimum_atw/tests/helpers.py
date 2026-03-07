from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_pdb_grain(out_dir: str | Path, grain: str) -> pd.DataFrame:
    frame = pd.read_parquet(Path(out_dir) / "pdb.parquet")
    return frame[frame["grain"].astype(str) == str(grain)].reset_index(drop=True)


def read_dataset_analysis(out_dir: str | Path, analysis: str) -> pd.DataFrame:
    frame = pd.read_parquet(Path(out_dir) / "dataset.parquet")
    return frame[frame["analysis"].astype(str) == str(analysis)].reset_index(drop=True)
