from __future__ import annotations

from typing import Any
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


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
        normalized = str(item).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


class RosettaInterfaceTarget(BaseModel):
    pair: Optional[tuple[str, str]] = None
    left_role: Optional[str] = None
    right_role: Optional[str] = None
    left_chains: list[str] = Field(default_factory=list)
    right_chains: list[str] = Field(default_factory=list)

    @field_validator("pair", mode="before")
    @classmethod
    def _normalize_pair(cls, value):
        if value is None:
            return None
        left, right = value
        normalized = (str(left).strip(), str(right).strip())
        if not normalized[0] or not normalized[1]:
            raise ValueError("rosetta interface pair labels must be non-empty")
        return normalized

    @field_validator("left_role", "right_role", mode="before")
    @classmethod
    def _normalize_role(cls, value):
        return _normalize_optional_str(value)

    @field_validator("left_chains", "right_chains", mode="before")
    @classmethod
    def _normalize_chains(cls, value):
        return _normalize_unique_str_list(value)

    @model_validator(mode="after")
    def _validate_target(self):
        left_by_role = self.left_role is not None
        right_by_role = self.right_role is not None
        left_by_chains = bool(self.left_chains)
        right_by_chains = bool(self.right_chains)

        if left_by_role == left_by_chains:
            raise ValueError("Rosetta left selector must use exactly one of left_role or left_chains")
        if right_by_role == right_by_chains:
            raise ValueError("Rosetta right selector must use exactly one of right_role or right_chains")

        if self.pair is None:
            left_label = self.left_role or f"chains_{'_'.join(self.left_chains)}"
            right_label = self.right_role or f"chains_{'_'.join(self.right_chains)}"
            self.pair = (left_label, right_label)
        return self


class Config(BaseModel):
    """Pipeline configuration with clear semantics for storage and execution options.
    
    Attributes:
        input_dir: Directory containing .pdb or .cif structure files
        out_dir: Directory for final outputs and intermediate working directories
        assembly_id: Structure assembly identifier (default: "1")
        roles: Semantic chain groupings {role_name: [chain_ids]}
        interface_pairs: Pairs of roles to analyze [(role1, role2), ...]
        manipulations: List of manipulation plugin names to apply in order
        plugins: List of analysis plugin names to run (run in parallel)
        contact_distance: Distance threshold for interface contacts (default: 5.0 Å)
        rosetta_executable: Optional path to Rosetta binary
        rosetta_database: Optional path to Rosetta database
        rosetta_score_jd2_executable: Optional path to Rosetta score_jd2 binary
        rosetta_preprocess_with_score_jd2: Whether to preprocess temporary Rosetta
            input PDBs with score_jd2 before InterfaceAnalyzer (default: False)
        rosetta_interface_targets: Optional Rosetta-specific interface selections.
            Each target can select each side by role or explicit chain list.
        rosetta_pack_input: Whether to run InterfaceAnalyzer in packed mode
            (default: True). Set to False for scientifically meaningful no-pack runs.
        rosetta_pack_separated: Whether to repack separated partners when packing
            is enabled (default: True)
        rosetta_compute_packstat: Whether to compute packstat-related metrics
            (default: True)
        rosetta_add_regular_scores_to_scorefile: Whether to request standard
            Rosetta score columns in the InterfaceAnalyzer scorefile (default: True)
        rosetta_packstat_oversample: Optional Rosetta packstat oversampling factor
            for more stable packstat estimates
        rosetta_atomic_burial_cutoff: Atomic burial cutoff used by Rosetta metrics
        rosetta_sasa_calculator_probe_radius: Probe radius passed to Rosetta SASA
            calculations (default: 1.4 Å)
        rosetta_interface_cutoff: Interface cutoff passed to Rosetta pose metrics
            (default: 8.0 Å)
        superimpose_reference_path: Optional PDB path for superimposition
        superimpose_on_chains: Chain IDs to use as superimposition reference
        keep_intermediate_outputs: If True, preserve _prepared/ and _plugins/ directories
            (default: False). Set to True only if re-running plugins or debugging.
            Saves ~30% disk space when False since temp directories are cleaned up.
        keep_prepared_structures: If True, cache prepared structure files in _prepared/structures/
            (default: False). Set to True only if re-running plugins separately.
            Saves ~40% disk I/O when False since raw structures are reloaded dynamically.
        dataset_analyses: List of dataset-level analysis plugin names
        dataset_analysis_params: Parameters for dataset analyses {plugin_name: {param: value}}
        dataset_annotations: Metadata annotations {key: value}
        numbering_roles: Which roles to apply numbering scheme to
        numbering_scheme: Numbering scheme for antibodies (default: "imgt")
        cdr_definition: CDR definition scheme (optional)
        checkpoint_enabled: Whether to enable write-ahead checkpoints during long runs
            (default: False). When True the pipeline persists each record as it is
            produced so a subsequent invocation can continue after a failure instead
            of starting over.
        checkpoint_interval: Number of structures to process between checkpoint
            flushes when checkpointing is enabled (default: 100). Smaller values
            improve recovery granularity at the cost of additional I/O.
    """
    input_dir: str
    out_dir: str
    assembly_id: str = "1"
    roles: dict[str, list[str]] = Field(default_factory=dict)
    interface_pairs: list[tuple[str, str]] = Field(default_factory=list)
    manipulations: list[str] = Field(default_factory=list)
    plugins: list[str] = Field(default_factory=list)
    contact_distance: float = 5.0
    rosetta_executable: Optional[str] = None
    rosetta_database: Optional[str] = None
    rosetta_score_jd2_executable: Optional[str] = None
    rosetta_preprocess_with_score_jd2: bool = False
    rosetta_interface_targets: list[RosettaInterfaceTarget] = Field(default_factory=list)
    rosetta_pack_input: bool = True
    rosetta_pack_separated: bool = True
    rosetta_compute_packstat: bool = True
    rosetta_add_regular_scores_to_scorefile: bool = True
    rosetta_packstat_oversample: Optional[int] = None
    rosetta_atomic_burial_cutoff: float = 0.01
    rosetta_sasa_calculator_probe_radius: float = 1.4
    rosetta_interface_cutoff: float = 8.0
    superimpose_reference_path: Optional[str] = None
    superimpose_on_chains: list[str] = Field(default_factory=list)
    keep_intermediate_outputs: bool = False
    keep_prepared_structures: bool = False
    dataset_analyses: list[str] = Field(default_factory=list)
    dataset_analysis_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    dataset_annotations: dict[str, str] = Field(default_factory=dict)
    numbering_roles: list[str] = Field(default_factory=list)
    numbering_scheme: str = "imgt"
    cdr_definition: Optional[str] = None

    # checkpoint options
    checkpoint_enabled: bool = False
    checkpoint_interval: int = 100

    @field_validator(
        "manipulations",
        "plugins",
        "superimpose_on_chains",
        "dataset_analyses",
        "numbering_roles",
        mode="before",
    )
    @classmethod
    def _normalize_name_lists(cls, value):
        return _normalize_unique_str_list(value)

    @field_validator("roles", mode="before")
    @classmethod
    def _normalize_roles(cls, value):
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
    def _normalize_interface_pairs(cls, value):
        if value is None:
            return []
        seen: set[tuple[str, str]] = set()
        out: list[tuple[str, str]] = []
        for pair in value:
            left, right = pair
            normalized = (str(left).strip(), str(right).strip())
            if not normalized[0] or not normalized[1] or normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
        return out

    @field_validator("dataset_analysis_params", mode="before")
    @classmethod
    def _normalize_dataset_analysis_params(cls, value):
        if value is None:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for analysis_name, params in dict(value).items():
            normalized_name = str(analysis_name).strip()
            if not normalized_name:
                continue
            normalized_params = dict(params or {})
            for key, param_value in list(normalized_params.items()):
                if isinstance(param_value, list):
                    normalized_params[key] = _normalize_unique_str_list(param_value)
            out[normalized_name] = normalized_params
        return out

    @field_validator("rosetta_interface_targets", mode="before")
    @classmethod
    def _normalize_rosetta_interface_targets(cls, value):
        if value is None:
            return []
        return list(value)

    @field_validator("numbering_scheme", mode="before")
    @classmethod
    def _normalize_numbering_scheme(cls, value):
        return str(value or "imgt").strip().lower()

    @field_validator("cdr_definition", mode="before")
    @classmethod
    def _normalize_cdr_definition(cls, value):
        normalized = _normalize_optional_str(value)
        if normalized is None:
            return None
        normalized = normalized.lower()
        return normalized or None

    @model_validator(mode="after")
    def _validate_numbering_options(self):
        allowed_schemes = {"imgt", "chothia", "kabat", "aho"}
        allowed_cdr_definitions = {"imgt", "chothia", "kabat", "north"}

        if self.numbering_scheme not in allowed_schemes:
            raise ValueError(
                f"numbering_scheme must be one of {sorted(allowed_schemes)}, got {self.numbering_scheme!r}"
            )
        if self.cdr_definition is not None and self.cdr_definition not in allowed_cdr_definitions:
            raise ValueError(
                f"cdr_definition must be one of {sorted(allowed_cdr_definitions)}, got {self.cdr_definition!r}"
            )
        if self.numbering_scheme == "aho" and self.cdr_definition is None:
            raise ValueError("cdr_definition is required when numbering_scheme is 'aho'")

        if self.rosetta_packstat_oversample is not None and self.rosetta_packstat_oversample < 1:
            raise ValueError("rosetta_packstat_oversample must be at least 1 when provided")
        if self.rosetta_atomic_burial_cutoff < 0:
            raise ValueError("rosetta_atomic_burial_cutoff must be non-negative")
        if self.rosetta_sasa_calculator_probe_radius <= 0:
            raise ValueError("rosetta_sasa_calculator_probe_radius must be positive")
        if self.rosetta_interface_cutoff <= 0:
            raise ValueError("rosetta_interface_cutoff must be positive")

        # checkpoint interval sanity
        if self.checkpoint_interval < 1:
            raise ValueError("checkpoint_interval must be at least 1")
        return self

    def rosetta_targets(self) -> list[RosettaInterfaceTarget]:
        if self.rosetta_interface_targets:
            return list(self.rosetta_interface_targets)
        return [
            RosettaInterfaceTarget(
                pair=(left_role, right_role),
                left_role=left_role,
                right_role=right_role,
            )
            for left_role, right_role in self.interface_pairs
        ]

    def interface_pairs_for_outputs(self) -> list[tuple[str, str]]:
        seen: set[tuple[str, str]] = set()
        out: list[tuple[str, str]] = []
        for pair in self.interface_pairs:
            if pair in seen:
                continue
            seen.add(pair)
            out.append(pair)
        for target in self.rosetta_targets():
            if target.pair in seen:
                continue
            seen.add(target.pair)
            out.append(target.pair)
        return out
