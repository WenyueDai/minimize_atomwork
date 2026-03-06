from __future__ import annotations

import math

import pandas as pd

from .base import BaseDatasetPlugin, DatasetAnalysisContext


def _shannon_entropy(values: list[str]) -> float:
    if not values:
        return 0.0
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    total = float(sum(counts.values()))
    entropy = 0.0
    for count in counts.values():
        p = float(count) / total
        entropy -= p * math.log2(p)
    return float(entropy)


class CDREntropyPlugin(BaseDatasetPlugin):
    name = "cdr_entropy"
    analysis_category = "antibody_analysis"

    def run(self, ctx: DatasetAnalysisContext) -> dict[str, int | str]:
        out_path = ctx.analysis_dir / "cdr_entropy.parquet"
        df = ctx.df_roles.copy()
        wanted = ["role", "abseq__cdr1_sequence", "abseq__cdr2_sequence", "abseq__cdr3_sequence"]
        missing = [col for col in wanted if col not in df.columns]
        if df.empty or missing:
            pd.DataFrame(
                columns=["role", "cdr", "n_sequences", "n_unique_sequences", "shannon_entropy"]
            ).to_parquet(out_path, index=False)
            return {
                "n_cdr_entropy_rows": 0,
                "cdr_entropy_output": str(out_path),
            }

        df = df[df["role"].notna()].copy()
        rows: list[dict[str, object]] = []
        for role_name in sorted(df["role"].astype(str).unique()):
            role_df = df[df["role"] == role_name].copy()
            for cdr_name in ("cdr1", "cdr2", "cdr3"):
                col = f"abseq__{cdr_name}_sequence"
                vals = [str(v).strip() for v in role_df[col].fillna("").tolist()]
                vals = [v for v in vals if v]
                rows.append(
                    {
                        "role": role_name,
                        "cdr": cdr_name,
                        "n_sequences": int(len(vals)),
                        "n_unique_sequences": int(len(set(vals))),
                        "shannon_entropy": float(_shannon_entropy(vals)),
                    }
                )

        out = pd.DataFrame(rows)
        out.to_parquet(out_path, index=False)
        return {
            "n_cdr_entropy_rows": int(len(out)),
            "cdr_entropy_output": str(out_path),
        }
