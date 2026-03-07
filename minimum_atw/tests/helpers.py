from __future__ import annotations

from pathlib import Path

import pandas as pd

from minimum_atw.core.output_files import dataset_output_path, pdb_output_path, read_output_metadata


def read_pdb_grain(out_dir: str | Path, grain: str) -> pd.DataFrame:
    resolved_out_dir = Path(out_dir)
    frame = pd.read_parquet(pdb_output_path(resolved_out_dir, metadata=read_output_metadata(resolved_out_dir)))
    return frame[frame["grain"].astype(str) == str(grain)].reset_index(drop=True)


def read_dataset_analysis(out_dir: str | Path, analysis: str) -> pd.DataFrame:
    resolved_out_dir = Path(out_dir)
    frame = pd.read_parquet(
        dataset_output_path(resolved_out_dir, metadata=read_output_metadata(resolved_out_dir))
    )
    return frame[frame["analysis"].astype(str) == str(analysis)].reset_index(drop=True)
