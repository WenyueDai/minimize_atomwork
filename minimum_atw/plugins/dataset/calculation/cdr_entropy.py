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


def _selected_regions_from_params(params: dict[str, object] | None) -> list[str]:
    requested = dict(params or {}).get("regions", [])
    default = ["cdr1", "cdr2", "cdr3"]
    if not isinstance(requested, list) or not requested:
        return default
    regions: list[str] = []
    for region in requested:
        normalized = str(region).strip().lower()
        if normalized in REGION_TO_COLUMN and normalized not in regions:
            regions.append(normalized)
    return regions or default


def _selected_regions(ctx: DatasetAnalysisContext) -> list[str]:
    return _selected_regions_from_params(dict(ctx.params or {}))


class CDREntropyPlugin(BaseDatasetPlugin):
    name = "cdr_entropy"
    analysis_category = "antibody_analysis"

    def required_columns(self, params: dict[str, object]) -> dict[str, list[str]]:
        regions = _selected_regions_from_params(params)
        return {
            "role": ["role", *[REGION_TO_COLUMN[region] for region in regions]],
        }

    def run(self, ctx: DatasetAnalysisContext) -> pd.DataFrame:
        df = ctx.df_roles.copy()
        regions = _selected_regions(ctx)
        wanted = ["role", *[REGION_TO_COLUMN[region] for region in regions]]
        missing = [col for col in wanted if col not in df.columns]
        if df.empty or missing:
            return pd.DataFrame(
                columns=["role", "region", "cdr", "source_column", "n_sequences", "n_unique_sequences", "shannon_entropy"]
            )

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

        return pd.DataFrame(rows)
