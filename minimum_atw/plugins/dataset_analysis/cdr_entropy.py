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


REGION_TO_COLUMN = {
    "cdr1": "abseq__cdr1_sequence",
    "cdr2": "abseq__cdr2_sequence",
    "cdr3": "abseq__cdr3_sequence",
    "sequence": "rolseq__sequence",
}


def _selected_roles(ctx: DatasetAnalysisContext, df: pd.DataFrame) -> list[str]:
    requested = dict(ctx.params or {}).get("roles", [])
    available = sorted(df["role"].astype(str).unique())
    if not isinstance(requested, list) or not requested:
        return available
    requested_roles = {str(role).strip() for role in requested if str(role).strip()}
    return [role for role in available if role in requested_roles]


def _selected_regions(ctx: DatasetAnalysisContext) -> list[str]:
    requested = dict(ctx.params or {}).get("regions", [])
    default = ["cdr1", "cdr2", "cdr3"]
    if not isinstance(requested, list) or not requested:
        return default
    regions: list[str] = []
    for region in requested:
        normalized = str(region).strip().lower()
        if normalized in REGION_TO_COLUMN and normalized not in regions:
            regions.append(normalized)
    return regions or default


class CDREntropyPlugin(BaseDatasetPlugin):
    name = "cdr_entropy"
    analysis_category = "antibody_analysis"

    def run(self, ctx: DatasetAnalysisContext) -> dict[str, int | str]:
        out_path = ctx.analysis_dir / "cdr_entropy.parquet"
        df = ctx.df_roles.copy()
        regions = _selected_regions(ctx)
        wanted = ["role", *[REGION_TO_COLUMN[region] for region in regions]]
        missing = [col for col in wanted if col not in df.columns]
        if df.empty or missing:
            pd.DataFrame(
                columns=["role", "region", "cdr", "source_column", "n_sequences", "n_unique_sequences", "shannon_entropy"]
            ).to_parquet(out_path, index=False)
            return {
                "n_cdr_entropy_rows": 0,
                "cdr_entropy_output": str(out_path),
            }

        df = df[df["role"].notna()].copy()
        rows: list[dict[str, object]] = []
        for role_name in _selected_roles(ctx, df):
            role_df = df[df["role"] == role_name].copy()
            for region_name in regions:
                col = REGION_TO_COLUMN[region_name]
                vals = [str(v).strip() for v in role_df[col].fillna("").tolist()]
                vals = [v for v in vals if v]
                rows.append(
                    {
                        "role": role_name,
                        "region": region_name,
                        "cdr": region_name if region_name.startswith("cdr") else "",
                        "source_column": col,
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
