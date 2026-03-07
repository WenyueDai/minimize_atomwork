from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re

import numpy as np
import pandas as pd
from biotite.structure.io import load_structure

from ....core.tables import empty_pdb_frame, rows_to_pdb_frame
from .base import BaseDatasetPlugin, DatasetAnalysisContext, DatasetAnalysisResult


def _cluster_mode(params: dict[str, object] | None) -> str:
    mode = str(dict(params or {}).get("mode", "interface_ca") or "interface_ca").strip().lower()
    aliases = {
        "interface_ca": "interface_ca",
        "interface_epitope_ca": "interface_ca",
        "superimposed_interface_ca": "superimposed_interface_ca",
    }
    if mode not in aliases:
        raise ValueError(
            "cluster.mode must be 'interface_ca', 'superimposed_interface_ca' "
            "(or legacy alias 'interface_epitope_ca')"
        )
    return aliases[mode]


def _distance_threshold(params: dict[str, object] | None) -> float:
    value = float(dict(params or {}).get("distance_threshold", 2.0) or 2.0)
    if value < 0:
        raise ValueError("cluster.distance_threshold must be non-negative")
    return value


def _center_points(params: dict[str, object] | None) -> bool:
    return bool(dict(params or {}).get("center", True))


def _selected_pairs(params: dict[str, object] | None) -> list[str]:
    raw = dict(params or {}).get("pairs", [])
    if not isinstance(raw, list) or not raw:
        single_pair = str(dict(params or {}).get("pair", "") or "").strip()
        return [single_pair] if single_pair else []
    out: list[str] = []
    for item in raw:
        normalized = str(item).strip()
        if normalized and normalized not in out:
            out.append(normalized)
    return out


def _interface_side(params: dict[str, object] | None) -> str:
    side = str(dict(params or {}).get("interface_side", "right") or "right").strip().lower()
    if side not in {"left", "right"}:
        raise ValueError("cluster.interface_side must be 'left' or 'right'")
    return side


def _job_column_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized or "cluster"


def _parse_residue_tokens(value: str) -> list[tuple[str, int]]:
    tokens = [token.strip() for token in str(value or "").split(";") if token.strip()]
    out: list[tuple[str, int]] = []
    for token in tokens:
        parts = token.split(":")
        if len(parts) < 2:
            continue
        chain_id = str(parts[0]).strip()
        try:
            res_id = int(parts[1])
        except Exception:
            continue
        if chain_id:
            out.append((chain_id, res_id))
    return out


def _centered(points: np.ndarray, *, center: bool) -> np.ndarray:
    arr = np.asarray(points, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 3:
        return np.empty((0, 3), dtype=float)
    if len(arr) == 0:
        return arr
    if not center:
        return arr
    return arr - np.mean(arr, axis=0, keepdims=True)


def _symmetric_chamfer(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) == 0 or len(right) == 0:
        return float("inf")
    diff = left[:, None, :] - right[None, :, :]
    dists = np.linalg.norm(diff, axis=2)
    return float(0.5 * (np.mean(np.min(dists, axis=1)) + np.mean(np.min(dists, axis=0))))


def _pairwise_distance_matrix(point_clouds: list[np.ndarray]) -> np.ndarray:
    n = len(point_clouds)
    dists = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            value = _symmetric_chamfer(point_clouds[i], point_clouds[j])
            dists[i, j] = value
            dists[j, i] = value
    return dists


def _average_linkage_clusters(distance_matrix: np.ndarray, threshold: float) -> list[list[int]]:
    clusters: list[list[int]] = [[idx] for idx in range(distance_matrix.shape[0])]
    if not clusters:
        return []

    while True:
        best_pair: tuple[int, int] | None = None
        best_distance = float("inf")
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                values = [distance_matrix[a, b] for a in clusters[i] for b in clusters[j]]
                distance = float(np.mean(values)) if values else float("inf")
                if distance < best_distance:
                    best_distance = distance
                    best_pair = (i, j)
        if best_pair is None or best_distance > threshold:
            break
        left_idx, right_idx = best_pair
        merged = sorted([*clusters[left_idx], *clusters[right_idx]])
        clusters = [cluster for idx, cluster in enumerate(clusters) if idx not in {left_idx, right_idx}]
        clusters.append(merged)

    clusters.sort(key=lambda members: (-len(members), members))
    return clusters


def _medoid_index(distance_matrix: np.ndarray, members: list[int]) -> int:
    if len(members) == 1:
        return members[0]
    best_member = members[0]
    best_score = float("inf")
    for member in members:
        score = float(np.mean([distance_matrix[member, other] for other in members]))
        if score < best_score:
            best_score = score
            best_member = member
    return best_member


def _resolve_load_path(value: object, *, out_dir: Path) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = (out_dir / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not candidate.exists():
        return None
    return str(candidate)


def _prepared_path_map(out_dir: Path, structures: pd.DataFrame | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    if structures is not None and not structures.empty and "path" in structures.columns and "prepared__path" in structures.columns:
        for source_path, prepared_path in zip(
            structures["path"].astype(str),
            structures["prepared__path"].astype(str),
            strict=False,
        ):
            resolved = _resolve_load_path(prepared_path, out_dir=out_dir)
            if resolved:
                out[str(source_path)] = resolved

    manifest_path = out_dir / "_prepared" / "prepared_manifest.parquet"
    if not manifest_path.exists():
        return out
    frame = pd.read_parquet(manifest_path)
    if frame.empty or "path" not in frame.columns or "prepared_path" not in frame.columns:
        return out
    for source_path, prepared_path in zip(frame["path"].astype(str), frame["prepared_path"].astype(str), strict=False):
        resolved = _resolve_load_path(prepared_path, out_dir=out_dir)
        if resolved and str(source_path) not in out:
            out[str(source_path)] = resolved
    return out


def _superimposed_path_map(out_dir: Path, structures: pd.DataFrame | None = None) -> dict[str, str]:
    if structures is None or structures.empty or "path" not in structures.columns:
        return {}
    out: dict[str, str] = {}
    has_transformed = "sup__transformed_path" in structures.columns
    has_prepare_superimpose = "sup__coordinates_applied" in structures.columns
    has_prepared_path = "prepared__path" in structures.columns
    for row in structures.itertuples(index=False):
        source_path = str(getattr(row, "path", "") or "")
        if not source_path:
            continue
        if has_transformed:
            transformed = _resolve_load_path(getattr(row, "sup__transformed_path", ""), out_dir=out_dir)
            if transformed:
                out[source_path] = transformed
                continue
        if has_prepare_superimpose and has_prepared_path:
            prepared = _resolve_load_path(getattr(row, "prepared__path", ""), out_dir=out_dir)
            if prepared and bool(getattr(row, "sup__coordinates_applied", False)):
                out[source_path] = prepared
    return out


@dataclass
class _PointCloudRecord:
    path: str
    assembly_id: str
    group_key: str
    point_cloud: np.ndarray
    metadata: dict[str, object]


@dataclass(frozen=True)
class _ClusterJob:
    name: str
    column_name: str
    mode: str
    interface_side: str
    distance_threshold: float
    center: bool
    selected_pairs: tuple[str, ...]


class _StructureLoader:
    def __init__(self):
        self._cache: dict[str, Any] = {}
        self._ca_lookup_cache: dict[str, dict[tuple[str, int], np.ndarray]] = {}
        self._point_cloud_cache: dict[tuple[str, tuple[tuple[str, int], ...]], np.ndarray] = {}

    def load(self, load_path: str):
        if load_path not in self._cache:
            self._cache[load_path] = load_structure(load_path)
        return self._cache[load_path]

    def ca_lookup(self, load_path: str) -> dict[tuple[str, int], np.ndarray]:
        if load_path in self._ca_lookup_cache:
            return self._ca_lookup_cache[load_path]
        arr = self.load(load_path)
        atom_names = arr.atom_name.astype(str)
        ca_atoms = arr[atom_names == "CA"]
        lookup: dict[tuple[str, int], np.ndarray] = {}
        for atom in ca_atoms:
            key = (str(atom.chain_id), int(atom.res_id))
            if key not in lookup:
                lookup[key] = np.asarray(atom.coord, dtype=float)
        self._ca_lookup_cache[load_path] = lookup
        return lookup

    def point_cloud(self, load_path: str, residues: list[tuple[str, int]]) -> np.ndarray:
        residue_key = tuple((str(chain_id), int(res_id)) for chain_id, res_id in residues)
        cache_key = (load_path, residue_key)
        if cache_key in self._point_cloud_cache:
            return self._point_cloud_cache[cache_key]

        coords: list[np.ndarray] = []
        ca_lookup = self.ca_lookup(load_path)
        for residue in residue_key:
            coord = ca_lookup.get(residue)
            if coord is not None:
                coords.append(coord)
        if not coords:
            point_cloud = np.empty((0, 3), dtype=float)
        else:
            point_cloud = np.vstack(coords)
        self._point_cloud_cache[cache_key] = point_cloud
        return point_cloud


def _ca_point_cloud_for_residues(loader: _StructureLoader, load_path: str, residues: list[tuple[str, int]]) -> np.ndarray:
    if not residues:
        return np.empty((0, 3), dtype=float)
    return loader.point_cloud(load_path, residues)


def _normalize_jobs(params: dict[str, object] | None) -> list[_ClusterJob]:
    raw_params = dict(params or {})
    raw_jobs = raw_params.get("jobs")
    if isinstance(raw_jobs, list) and raw_jobs:
        jobs: list[_ClusterJob] = []
        for index, raw_job in enumerate(raw_jobs, start=1):
            job_params = dict(raw_job or {})
            mode = _cluster_mode(job_params)
            side = _interface_side(job_params)
            selected_pairs = tuple(_selected_pairs(job_params))
            default_name = f"{side}_{index:02d}"
            name = str(job_params.get("name", default_name) or default_name).strip() or default_name
            jobs.append(
                _ClusterJob(
                    name=name,
                    column_name=_job_column_name(name),
                    mode=mode,
                    interface_side=side,
                    distance_threshold=_distance_threshold(job_params),
                    center=_center_points(job_params),
                    selected_pairs=selected_pairs,
                )
            )
        seen: set[str] = set()
        for job in jobs:
            if job.column_name in seen:
                raise ValueError(f"Duplicate cluster job name after normalization: '{job.name}'")
            seen.add(job.column_name)
        return jobs

    mode = _cluster_mode(raw_params)
    distance_threshold = _distance_threshold(raw_params)
    center = _center_points(raw_params)
    selected_pairs = tuple(_selected_pairs(raw_params))
    explicit_side = raw_params.get("interface_side")
    if explicit_side is None:
        jobs = [
            _ClusterJob(
                name="left",
                column_name="left",
                mode=mode,
                interface_side="left",
                distance_threshold=distance_threshold,
                center=center,
                selected_pairs=selected_pairs,
            ),
            _ClusterJob(
                name="right",
                column_name="right",
                mode=mode,
                interface_side="right",
                distance_threshold=distance_threshold,
                center=center,
                selected_pairs=selected_pairs,
            ),
        ]
    else:
        jobs = [
            _ClusterJob(
                name="default",
                column_name="default",
                mode=mode,
                interface_side=_interface_side(raw_params),
                distance_threshold=distance_threshold,
                center=center,
                selected_pairs=selected_pairs,
            )
        ]

    seen: set[str] = set()
    for job in jobs:
        if job.column_name in seen:
            raise ValueError(f"Duplicate cluster job name after normalization: '{job.name}'")
        seen.add(job.column_name)
    return jobs


def _cluster_rows(records: list[_PointCloudRecord], *, threshold: float) -> list[dict[str, object]]:
    if not records:
        return []
    point_clouds = [record.point_cloud for record in records]
    distance_matrix = _pairwise_distance_matrix(point_clouds)
    clusters = _average_linkage_clusters(distance_matrix, threshold)

    rows: list[dict[str, object]] = []
    for cluster_index, members in enumerate(clusters, start=1):
        representative_idx = _medoid_index(distance_matrix, members)
        representative = records[representative_idx]
        cluster_size = len(members)
        for member_idx in members:
            record = records[member_idx]
            rows.append(
                {
                    **record.metadata,
                    "cluster_id": int(cluster_index),
                    "cluster_size": int(cluster_size),
                    "cluster_representative_path": representative.path,
                    "distance_to_representative": float(distance_matrix[member_idx, representative_idx]),
                }
            )
    return rows


class ClusterPlugin(BaseDatasetPlugin):
    name = "cluster"
    analysis_category = "cluster"

    def required_columns(self, params: dict[str, object]) -> dict[str, list[str]]:
        jobs = _normalize_jobs(params)
        residue_columns = sorted({f"iface__{job.interface_side}_interface_residues" for job in jobs})
        required = {
            "interface": [
                "path",
                "assembly_id",
                "pair",
                "role_left",
                "role_right",
                *residue_columns,
            ]
        }
        if any(job.mode == "superimposed_interface_ca" for job in jobs):
            required["structure"] = [
                "path",
                "prepared__path",
                "sup__coordinates_applied",
                "sup__transformed_path",
            ]
        return required

    def run(self, ctx: DatasetAnalysisContext) -> pd.DataFrame | DatasetAnalysisResult:
        params = dict(ctx.params or {})
        jobs = _normalize_jobs(params)
        structures = ctx.grains.get("structure", pd.DataFrame())
        prepared_map = _prepared_path_map(ctx.out_dir, structures)
        superimposed_map = _superimposed_path_map(ctx.out_dir, structures)
        loader = _StructureLoader()
        df = ctx.df_interfaces.copy()
        required_columns = {f"iface__{job.interface_side}_interface_residues" for job in jobs}
        if df.empty or not required_columns.issubset(df.columns):
            return DatasetAnalysisResult(dataset_frame=pd.DataFrame(columns=["analysis"]), pdb_frame=empty_pdb_frame())

        rows: list[dict[str, object]] = []
        residue_cache: dict[str, list[tuple[str, int]]] = {}
        for job in jobs:
            residue_column = f"iface__{job.interface_side}_interface_residues"
            job_df = df
            if job.selected_pairs:
                job_df = job_df[job_df["pair"].astype(str).isin(set(job.selected_pairs))].copy()

            records_by_group: dict[str, list[_PointCloudRecord]] = {}
            for row in job_df.itertuples(index=False):
                path = str(getattr(row, "path", "") or "")
                assembly_id = str(getattr(row, "assembly_id", "") or "")
                pair = str(getattr(row, "pair", "") or "")
                residue_tokens = str(getattr(row, residue_column, "") or "")
                residues = residue_cache.setdefault(residue_tokens, _parse_residue_tokens(residue_tokens))
                if job.mode == "superimposed_interface_ca":
                    load_path = superimposed_map.get(path)
                    if load_path is None:
                        raise ValueError(
                            "cluster.mode='superimposed_interface_ca' requires either "
                            "`sup__transformed_path` from persisted superimpose_homology outputs "
                            "or a saved prepared structure produced by `superimpose_to_reference`"
                        )
                else:
                    load_path = prepared_map.get(path, path)
                point_cloud = _centered(_ca_point_cloud_for_residues(loader, load_path, residues), center=job.center)
                if not path or len(point_cloud) == 0:
                    continue
                records_by_group.setdefault(pair, []).append(
                    _PointCloudRecord(
                        path=path,
                        assembly_id=assembly_id,
                        group_key=pair,
                        point_cloud=point_cloud,
                        metadata={
                            "job": job.name,
                            "job_column": job.column_name,
                            "mode": job.mode,
                            "group_key": pair,
                            "pair": pair,
                            "path": path,
                            "assembly_id": assembly_id,
                            "role_left": str(getattr(row, "role_left", "") or ""),
                            "role_right": str(getattr(row, "role_right", "") or ""),
                            "interface_side": job.interface_side,
                            "n_points": int(len(point_cloud)),
                        },
                    )
                )
            for group_key in sorted(records_by_group):
                rows.extend(_cluster_rows(records_by_group[group_key], threshold=job.distance_threshold))
        if not rows:
            return DatasetAnalysisResult(dataset_frame=pd.DataFrame(columns=["analysis"]), pdb_frame=empty_pdb_frame())

        merged_rows: dict[tuple[str, str, str, str, str], dict[str, object]] = {}
        for row in rows:
            key = (
                str(row.get("path", "") or ""),
                str(row.get("assembly_id", "") or ""),
                str(row.get("pair", "") or ""),
                str(row.get("role_left", "") or ""),
                str(row.get("role_right", "") or ""),
            )
            out = merged_rows.setdefault(
                key,
                {
                    "path": key[0],
                    "assembly_id": key[1],
                    "grain": "interface",
                    "chain_id": "",
                    "role": "",
                    "pair": key[2],
                    "role_left": key[3],
                    "role_right": key[4],
                },
            )
            column_stem = f"cluster__{row['job_column']}"
            out[f"{column_stem}_cluster_id"] = int(row["cluster_id"])
            out[f"{column_stem}_cluster_size"] = int(row["cluster_size"])
            out[f"{column_stem}_representative_path"] = str(row["cluster_representative_path"])
            out[f"{column_stem}_distance_to_representative"] = float(row["distance_to_representative"])
            out[f"{column_stem}_n_points"] = int(row["n_points"])
            out[f"{column_stem}_interface_side"] = str(row["interface_side"])
            out[f"{column_stem}_mode"] = str(row["mode"])

        return DatasetAnalysisResult(dataset_frame=pd.DataFrame(columns=["analysis"]), pdb_frame=rows_to_pdb_frame(list(merged_rows.values())))
