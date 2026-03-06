from __future__ import annotations

import pandas as pd

from .base import BaseDatasetPlugin, DatasetAnalysisContext


class InterfaceSummaryPlugin(BaseDatasetPlugin):
    name = "interface_summary"
    analysis_category = "interface_analysis"

    def run(self, ctx: DatasetAnalysisContext) -> dict[str, int | str]:
        df = ctx.df_interfaces.copy()
        out_path = ctx.analysis_dir / "interface_summary.parquet"

        if df.empty:
            pd.DataFrame(
                columns=["pair", "n_rows", "n_unique_paths", "mean_contact_atom_pairs", "mean_left_interface_residues", "mean_right_interface_residues"]
            ).to_parquet(out_path, index=False)
            return {
                "n_interface_summary_rows": 0,
                "interface_summary_output": str(out_path),
            }

        group_cols = ["pair"]
        for required in (
            "iface__n_contact_atom_pairs",
            "iface__n_left_interface_residues",
            "iface__n_right_interface_residues",
        ):
            if required not in df.columns:
                df[required] = pd.NA

        out = (
            df.groupby(group_cols, dropna=False)
            .agg(
                n_rows=("pair", "size"),
                n_unique_paths=("path", "nunique"),
                mean_contact_atom_pairs=("iface__n_contact_atom_pairs", "mean"),
                mean_left_interface_residues=("iface__n_left_interface_residues", "mean"),
                mean_right_interface_residues=("iface__n_right_interface_residues", "mean"),
            )
            .reset_index()
        )
        out.to_parquet(out_path, index=False)
        return {
            "n_interface_summary_rows": int(len(out)),
            "interface_summary_output": str(out_path),
        }
