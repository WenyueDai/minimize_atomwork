from __future__ import annotations

import math

import pandas as pd

from .base import BaseDatasetPlugin, DatasetAnalysisContext
from ...pdb.calculation.antibody_analysis.antibody_numbering import cdr_position_labels


def _shannon_entropy(values: list[str]) -> float:
    if not values:
        return 0.0
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return _shannon_entropy_from_counts(counts)


def _shannon_entropy_from_counts(counts: dict[str, int]) -> float:
    if not counts:
        return 0.0
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
DEFAULT_COLUMNS = [
    "role",
    "region",
    "row_kind",
    "position",
    "source_column",
    "n_sequences_total",
    "n_observations",
    "n_unique",
    "shannon_entropy",
    "occupancy_fraction",
]


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


def _string_value(value: object) -> str:
    if value is None:
        return ""
    try:
        missing = pd.isna(value)
    except Exception:
        missing = False
    if bool(missing):
        return ""
    return str(value).strip()


def _normalize_cdr_definition(value: object) -> str | None:
    normalized = _string_value(value).lower()
    return normalized or None


def _summary_row(role_name: str, region_name: str, source_column: str, values: list[str]) -> dict[str, object]:
    return {
        "role": role_name,
        "region": region_name,
        "row_kind": "summary",
        "position": "",
        "source_column": source_column,
        "n_sequences_total": int(len(values)),
        "n_observations": int(len(values)),
        "n_unique": int(len(set(values))),
        "shannon_entropy": float(_shannon_entropy(values)),
        "occupancy_fraction": 1.0 if values else 0.0,
    }


def _position_rows(role_name: str, region_name: str, source_column: str, role_df: pd.DataFrame) -> list[dict[str, object]]:
    position_counts: dict[str, dict[str, int]] = {}
    position_order: list[str] = []
    n_sequences_total = 0

    for row in role_df.itertuples(index=False):
        cdr_sequence = _string_value(getattr(row, source_column, ""))
        full_sequence = _string_value(getattr(row, "rolseq__sequence", ""))
        if not cdr_sequence or not full_sequence:
            continue

        scheme = _string_value(getattr(row, "abseq__numbering_scheme", "")) or "imgt"
        cdr_definition = _normalize_cdr_definition(getattr(row, "abseq__cdr_definition", None))
        labels = cdr_position_labels(full_sequence, scheme=scheme, cdr_definition=cdr_definition)[region_name]
        if len(labels) != len(cdr_sequence):
            raise RuntimeError(
                f"CDR numbering mismatch for role={role_name!r} region={region_name!r}: "
                f"{len(labels)} numbered positions != {len(cdr_sequence)} residues"
            )

        n_sequences_total += 1
        for label, aa in zip(labels, cdr_sequence, strict=False):
            counts = position_counts.setdefault(label, {})
            if label not in position_order:
                position_order.append(label)
            counts[aa] = counts.get(aa, 0) + 1

    rows: list[dict[str, object]] = []
    for label in position_order:
        counts = position_counts[label]
        observed = int(sum(counts.values()))
        rows.append(
            {
                "role": role_name,
                "region": region_name,
                "row_kind": "position",
                "position": label,
                "source_column": source_column,
                "n_sequences_total": int(n_sequences_total),
                "n_observations": observed,
                "n_unique": int(len(counts)),
                "shannon_entropy": float(_shannon_entropy_from_counts(counts)),
                "occupancy_fraction": float(observed / n_sequences_total) if n_sequences_total else 0.0,
            }
        )
    return rows


class CDREntropyPlugin(BaseDatasetPlugin):
    name = "cdr_entropy"
    analysis_category = "antibody_analysis"

    def required_columns(self, params: dict[str, object]) -> dict[str, list[str]]:
        regions = _selected_regions_from_params(params)
        required = ["role"]
        if "sequence" in regions or any(region.startswith("cdr") for region in regions):
            required.append("rolseq__sequence")
        if any(region.startswith("cdr") for region in regions):
            required.extend(["abseq__numbering_scheme", "abseq__cdr_definition"])
            required.extend(REGION_TO_COLUMN[region] for region in regions if region.startswith("cdr"))
        return {
            "role": list(dict.fromkeys(required)),
        }

    def run(self, ctx: DatasetAnalysisContext) -> pd.DataFrame:
        df = ctx.df_roles.copy()
        regions = _selected_regions(ctx)
        wanted = self.required_columns(dict(ctx.params or {})).get("role", ["role"])
        missing = [col for col in wanted if col not in df.columns]
        if df.empty or missing:
            return pd.DataFrame(columns=DEFAULT_COLUMNS)

        df = df[df["role"].notna()].copy()
        rows: list[dict[str, object]] = []
        for role_name in _selected_roles(ctx, df):
            role_df = df[df["role"] == role_name].copy()
            for region_name in regions:
                source_column = REGION_TO_COLUMN[region_name]
                if region_name == "sequence":
                    values = [_string_value(value) for value in role_df[source_column].tolist()]
                    values = [value for value in values if value]
                    if values:
                        rows.append(_summary_row(role_name, region_name, source_column, values))
                    continue
                rows.extend(_position_rows(role_name, region_name, source_column, role_df))

        if not rows:
            return pd.DataFrame(columns=DEFAULT_COLUMNS)
        return pd.DataFrame(rows, columns=DEFAULT_COLUMNS)
