from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .output_files import (
    DEFAULT_DATASET_OUTPUT_NAME,
    DEFAULT_PDB_OUTPUT_NAME,
    normalize_output_filename,
)

PREPARE_SECTION_ORDER = ("quality_control", "structure")
GRAIN_ORDER = ("pdb", "dataset")
DATASET_ANALYSIS_MODES = {"post_merge", "per_chunk", "both"}
NUMBERING_SCHEMES = {"imgt", "chothia", "kabat", "aho"}
CDR_DEFINITIONS = {"imgt", "north", "kabat"}
CLASH_SCOPES = {"all", "inter_chain", "interface_only"}
SLURM_MODES = {"auto", "mixed", "staged"}


def _normalize_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_unique_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        normalized = _normalize_optional_str(item)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _normalize_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    out: list[str] = []
    for item in value:
        normalized = _normalize_optional_str(item)
        if normalized is None:
            continue
        out.append(normalized)
    return out


def _normalize_pair(value: Any) -> tuple[str, str] | None:
    if value is None:
        return None
    try:
        left_raw, right_raw = value
    except Exception as exc:
        raise ValueError("pairs must contain exactly two values") from exc
    left = _normalize_optional_str(left_raw)
    right = _normalize_optional_str(right_raw)
    if left is None or right is None:
        return None
    return left, right


def _normalize_pairs(value: Any) -> list[tuple[str, str]]:
    if value is None:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for raw_pair in value:
        normalized = _normalize_pair(raw_pair)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _normalize_string_mapping(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    out: dict[str, str] = {}
    for raw_key, raw_item in dict(value).items():
        key = _normalize_optional_str(raw_key)
        item = _normalize_optional_str(raw_item)
        if key is None or item is None:
            continue
        out[key] = item
    return out


def _normalize_nested_mapping(value: Any) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for raw_key, raw_item in dict(value).items():
        key = _normalize_optional_str(raw_key)
        if key is None:
            continue
        out[key] = dict(raw_item or {})
    return out


def _normalize_prepare_section(value: str | None) -> str:
    normalized = str(value or "structure").strip().lower()
    aliases = {
        "quality_control": "quality_control",
        "quality_controls": "quality_control",
        "structure": "structure",
        "structure_manipulation": "structure",
        "structure_manipulations": "structure",
    }
    return aliases.get(normalized, "structure")


def _chains_label(chain_ids: list[str]) -> str | None:
    if not chain_ids:
        return None
    return "chains_" + "_".join(chain_ids)


class RosettaTarget(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pair: tuple[str, str]
    left_role: str | None = None
    right_role: str | None = None
    left_chains: list[str] = Field(default_factory=list)
    right_chains: list[str] = Field(default_factory=list)


class SlurmConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chunk_size: int | None = None
    plan_dir: str | None = None
    workdir: str | None = None
    python_bin: str | None = None
    mode: str = "auto"
    array_limit: int | None = None
    log_dir: str | None = None
    sbatch_common_args: list[str] = Field(default_factory=list)
    sbatch_mixed_args: list[str] = Field(default_factory=list)
    sbatch_cpu_args: list[str] = Field(default_factory=list)
    sbatch_gpu_args: list[str] = Field(default_factory=list)
    sbatch_merge_args: list[str] = Field(default_factory=list)

    @field_validator("chunk_size", "array_limit", mode="before")
    @classmethod
    def _normalize_optional_ints(cls, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
        return int(value)

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> str:
        return (_normalize_optional_str(value) or "auto").lower()

    @field_validator("plan_dir", "workdir", "python_bin", "log_dir", mode="before")
    @classmethod
    def _normalize_paths(cls, value: Any) -> str | None:
        normalized = _normalize_optional_str(value)
        if normalized is None:
            return None
        return str(Path(normalized).expanduser())

    @field_validator(
        "sbatch_common_args",
        "sbatch_mixed_args",
        "sbatch_cpu_args",
        "sbatch_gpu_args",
        "sbatch_merge_args",
        mode="before",
    )
    @classmethod
    def _normalize_sbatch_arg_lists(cls, value: Any) -> list[str]:
        return _normalize_str_list(value)

    @model_validator(mode="after")
    def _validate_values(self) -> "SlurmConfig":
        if self.mode not in SLURM_MODES:
            raise ValueError(f"slurm.mode must be one of {sorted(SLURM_MODES)}")
        if self.chunk_size is not None and self.chunk_size < 1:
            raise ValueError("slurm.chunk_size must be at least 1")
        if self.array_limit is not None and self.array_limit < 1:
            raise ValueError("slurm.array_limit must be at least 1")
        return self


class Config(BaseModel):
    """Runtime configuration for prepare, plugin execution, and dataset analyses.

    Extra fields are preserved so third-party plugins can read plugin-specific
    configuration directly from the shared config object.
    """

    model_config = ConfigDict(extra="allow")

    input_dir: str
    out_dir: str
    assembly_id: str = "1"
    roles: dict[str, list[str]] = Field(default_factory=dict)
    interface_pairs: list[tuple[str, str]] = Field(default_factory=list)

    manipulations: list[dict[str, str]] = Field(default_factory=list)
    plugins: list[str] = Field(default_factory=list)
    dataset_analyses: list[str] = Field(default_factory=list)
    pdb_output_name: str = DEFAULT_PDB_OUTPUT_NAME
    dataset_output_name: str = DEFAULT_DATASET_OUTPUT_NAME

    clash_distance: float = 2.0
    clash_scope: str = "all"
    contact_distance: float = 5.0
    interface_cell_size: float | None = None
    abepitope_atom_radius: float = 4.0

    keep_intermediate_outputs: bool = False
    keep_prepared_structures: bool = False
    checkpoint_enabled: bool = False
    checkpoint_interval: int = 100
    cleanup_prepared_after_dataset_analysis: bool = False

    dataset_analysis_mode: str = "post_merge"
    dataset_analysis_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    plugin_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    dataset_annotations: dict[str, str] = Field(default_factory=dict)
    chunk_cpu_capacity: int | None = None
    cpu_workers: int = 1
    gpu_workers: int = 0
    gpu_devices: list[str] = Field(default_factory=list)
    slurm: SlurmConfig = Field(default_factory=SlurmConfig)

    superimpose_reference_path: str | None = None
    superimpose_on_chains: list[str] = Field(default_factory=list)

    reference_dataset_dir: str | None = None

    numbering_roles: list[str] = Field(default_factory=list)
    numbering_scheme: str = "imgt"
    cdr_definition: str | None = None

    rosetta_executable: str | None = None
    rosetta_database: str | None = None
    rosetta_score_jd2_executable: str | None = None
    rosetta_relax_executable: str | None = None
    rosetta_preprocess_with_score_jd2: bool = False
    rosetta_preprocess: bool = True
    rosetta_interface_targets: list[RosettaTarget] = Field(default_factory=list)
    rosetta_pack_input: bool = True
    rosetta_pack_separated: bool = True
    rosetta_compute_packstat: bool = True
    rosetta_add_regular_scores_to_scorefile: bool = True
    rosetta_packstat_oversample: int | None = None
    rosetta_atomic_burial_cutoff: float = 0.01
    rosetta_sasa_calculator_probe_radius: float = 1.4
    rosetta_interface_cutoff: float = 8.0

    @field_validator(
        "plugins",
        "dataset_analyses",
        "numbering_roles",
        "superimpose_on_chains",
        "gpu_devices",
        mode="before",
    )
    @classmethod
    def _normalize_name_lists(cls, value: Any) -> list[str]:
        return _normalize_unique_str_list(value)

    @field_validator("manipulations", mode="before")
    @classmethod
    def _normalize_manipulations(cls, value: Any) -> list[dict[str, str]]:
        if value is None:
            return []
        out: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("manipulations must be list of dicts")
            name = _normalize_optional_str(item.get("name"))
            grain = _normalize_optional_str(item.get("grain"))
            if name is None or grain is None:
                continue
            if grain not in {"pdb", "dataset"}:
                raise ValueError(f"grain must be 'pdb' or 'dataset', got {grain}")
            key = (name, grain)
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": name, "grain": grain})
        return out

    @field_validator("roles", mode="before")
    @classmethod
    def _normalize_roles(cls, value: Any) -> dict[str, list[str]]:
        if value is None:
            return {}
        out: dict[str, list[str]] = {}
        for role_name, chain_ids in dict(value).items():
            normalized_role = _normalize_optional_str(role_name)
            if normalized_role is None:
                continue
            out[normalized_role] = _normalize_unique_str_list(chain_ids or [])
        return out

    @field_validator("interface_pairs", mode="before")
    @classmethod
    def _normalize_interface_pairs(cls, value: Any) -> list[tuple[str, str]]:
        return _normalize_pairs(value)

    @field_validator("assembly_id", mode="before")
    @classmethod
    def _normalize_assembly_id(cls, value: Any) -> str:
        return _normalize_optional_str(value) or "1"

    @field_validator(
        "dataset_analysis_mode",
        "clash_scope",
        "numbering_scheme",
        "cdr_definition",
        mode="before",
    )
    @classmethod
    def _normalize_optional_lowercase(cls, value: Any) -> str | None:
        normalized = _normalize_optional_str(value)
        if normalized is None:
            return None
        return normalized.lower()

    @field_validator(
        "superimpose_reference_path",
        "reference_dataset_dir",
        "rosetta_executable",
        "rosetta_database",
        "rosetta_score_jd2_executable",
        "rosetta_relax_executable",
        mode="before",
    )
    @classmethod
    def _normalize_paths(cls, value: Any) -> str | None:
        normalized = _normalize_optional_str(value)
        if normalized is None:
            return None
        return str(Path(normalized).expanduser())

    @field_validator("dataset_analysis_params", "plugin_params", mode="before")
    @classmethod
    def _normalize_dataset_analysis_params(cls, value: Any) -> dict[str, dict[str, Any]]:
        return _normalize_nested_mapping(value)

    @field_validator("chunk_cpu_capacity", "cpu_workers", "gpu_workers", mode="before")
    @classmethod
    def _normalize_worker_counts(cls, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
        return int(value)

    @field_validator("dataset_annotations", mode="before")
    @classmethod
    def _normalize_dataset_annotations(cls, value: Any) -> dict[str, str]:
        return _normalize_string_mapping(value)

    @field_validator("pdb_output_name", mode="before")
    @classmethod
    def _normalize_pdb_output_name(cls, value: Any) -> str:
        return normalize_output_filename(value, default=DEFAULT_PDB_OUTPUT_NAME, label="pdb_output_name")

    @field_validator("dataset_output_name", mode="before")
    @classmethod
    def _normalize_dataset_output_name(cls, value: Any) -> str:
        return normalize_output_filename(
            value,
            default=DEFAULT_DATASET_OUTPUT_NAME,
            label="dataset_output_name",
        )

    @field_validator("rosetta_interface_targets", mode="before")
    @classmethod
    def _normalize_rosetta_targets(cls, value: Any) -> list[RosettaTarget]:
        if value is None:
            return []
        seen: set[tuple[Any, ...]] = set()
        out: list[RosettaTarget] = []
        for raw_target in value:
            raw = dict(raw_target)
            pair = _normalize_pair(raw.get("pair"))
            left_role = _normalize_optional_str(raw.get("left_role"))
            right_role = _normalize_optional_str(raw.get("right_role"))
            left_chains = _normalize_unique_str_list(raw.get("left_chains"))
            right_chains = _normalize_unique_str_list(raw.get("right_chains"))

            if left_role is None and not left_chains:
                raise ValueError("rosetta_interface_targets require a left_role or left_chains selection")
            if right_role is None and not right_chains:
                raise ValueError("rosetta_interface_targets require a right_role or right_chains selection")

            if pair is None:
                pair_left = left_role or _chains_label(left_chains)
                pair_right = right_role or _chains_label(right_chains)
                if pair_left is None or pair_right is None:
                    raise ValueError("could not derive pair label for rosetta target")
                pair = (pair_left, pair_right)

            target = RosettaTarget(
                pair=pair,
                left_role=left_role,
                right_role=right_role,
                left_chains=left_chains,
                right_chains=right_chains,
            )
            dedupe_key = (
                target.pair,
                target.left_role,
                target.right_role,
                tuple(target.left_chains),
                tuple(target.right_chains),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            out.append(target)
        return out

    @model_validator(mode="after")
    def _validate_runtime_options(self) -> "Config":
        if self.dataset_analysis_mode not in DATASET_ANALYSIS_MODES:
            raise ValueError(
                f"dataset_analysis_mode must be one of {sorted(DATASET_ANALYSIS_MODES)}"
            )
        if self.numbering_scheme not in NUMBERING_SCHEMES:
            raise ValueError(f"numbering_scheme must be one of {sorted(NUMBERING_SCHEMES)}")
        if self.cdr_definition is not None and self.cdr_definition not in CDR_DEFINITIONS:
            raise ValueError(f"cdr_definition must be one of {sorted(CDR_DEFINITIONS)}")
        if self.numbering_scheme == "aho" and self.cdr_definition is None:
            raise ValueError("numbering_scheme='aho' requires cdr_definition")
        if self.checkpoint_interval < 1:
            raise ValueError("checkpoint_interval must be at least 1")
        if self.chunk_cpu_capacity is not None and self.chunk_cpu_capacity < 1:
            raise ValueError("chunk_cpu_capacity must be at least 1")
        if self.cpu_workers < 1:
            raise ValueError("cpu_workers must be at least 1")
        if self.gpu_workers < 0:
            raise ValueError("gpu_workers must be at least 0")
        if self.clash_distance <= 0:
            raise ValueError("clash_distance must be positive")
        if self.clash_scope not in CLASH_SCOPES:
            raise ValueError(f"clash_scope must be one of {sorted(CLASH_SCOPES)}")
        if self.rosetta_packstat_oversample is not None and self.rosetta_packstat_oversample < 1:
            raise ValueError("rosetta_packstat_oversample must be at least 1")
        if self.pdb_output_name == self.dataset_output_name:
            raise ValueError("pdb_output_name and dataset_output_name must be different")
        prepare_names = {item["name"] for item in self.manipulations}
        if "superimpose_to_reference" in prepare_names or "rosetta_preprocess" in prepare_names:
            self.keep_prepared_structures = True
        if "superimpose_to_reference" in prepare_names and "superimpose_homology" in self.plugins:
            raise ValueError(
                "superimpose_to_reference and superimpose_homology cannot be enabled together; "
                "both write sup__* columns, so choose either prepare-stage coordinate rewriting "
                "or plugin-stage superposition metrics"
            )
        return self

    def prepare_names_by_grain(self) -> dict[str, list[str]]:
        grouped = {"pdb": [], "dataset": []}
        for item in self.manipulations:
            name = item["name"]
            grain = item["grain"]
            grouped[grain].append(name)
        return grouped

    def ordered_prepare_names(self) -> list[str]:
        grouped = self.prepare_names_by_grain()
        ordered: list[str] = []
        for grain in GRAIN_ORDER:
            ordered.extend(grouped[grain])
        return ordered

    def chunk_dataset_analyses(self) -> list[str]:
        if self.dataset_analysis_mode not in {"per_chunk", "both"}:
            return []
        return list(self.dataset_analyses)

    def should_run_post_merge_dataset_analyses(self) -> bool:
        return bool(self.dataset_analyses) and self.dataset_analysis_mode in {"post_merge", "both"}

    def chunk_config(self, *, input_dir: str | Path, out_dir: str | Path) -> "Config":
        dataset_analyses = self.chunk_dataset_analyses()
        return self.model_copy(
            update={
                "input_dir": str(Path(input_dir)),
                "out_dir": str(Path(out_dir)),
                "keep_intermediate_outputs": False,
                "dataset_analyses": dataset_analyses,
                "dataset_analysis_params": self.dataset_analysis_params if dataset_analyses else {},
                "dataset_annotations": self.dataset_annotations if dataset_analyses else {},
            }
        )

    def rosetta_targets(self) -> list[RosettaTarget]:
        if self.rosetta_interface_targets:
            return list(self.rosetta_interface_targets)
        return [
            RosettaTarget(pair=pair, left_role=pair[0], right_role=pair[1])
            for pair in self.interface_pairs
        ]

    def interface_pairs_for_outputs(self) -> list[tuple[str, str]]:
        pairs = list(self.interface_pairs)
        seen = set(pairs)
        for target in self.rosetta_targets():
            if target.pair in seen:
                continue
            seen.add(target.pair)
            pairs.append(target.pair)
        return pairs

    def merge_compatibility(self) -> dict[str, Any]:
        excluded = {
            "input_dir",
            "out_dir",
            "keep_intermediate_outputs",
            "keep_prepared_structures",
            "checkpoint_enabled",
            "checkpoint_interval",
            "cleanup_prepared_after_dataset_analysis",
            "dataset_analyses",
            "dataset_analysis_mode",
            "dataset_analysis_params",
            "plugin_params",
            "reference_dataset_dir",
            "dataset_annotations",
            "chunk_cpu_capacity",
            "cpu_workers",
            "gpu_workers",
            "gpu_devices",
            "slurm",
            "pdb_output_name",
            "dataset_output_name",
        }
        return {
            key: value
            for key, value in self.model_dump(mode="json").items()
            if key not in excluded
        }
