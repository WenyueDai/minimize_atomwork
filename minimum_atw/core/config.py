from __future__ import annotations

from typing import Any
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


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

    @field_validator("roles", mode="before")
    @classmethod
    def _normalize_roles(cls, value):
        if value is None:
            return {}
        out: dict[str, list[str]] = {}
        for role_name, chain_ids in dict(value).items():
            normalized_role = str(role_name).strip()
            if not normalized_role:
                continue
            seen: set[str] = set()
            normalized_chain_ids: list[str] = []
            for chain_id in chain_ids or []:
                normalized_chain = str(chain_id).strip()
                if not normalized_chain or normalized_chain in seen:
                    continue
                seen.add(normalized_chain)
                normalized_chain_ids.append(normalized_chain)
            out[normalized_role] = normalized_chain_ids
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
                    seen: set[str] = set()
                    items: list[str] = []
                    for item in param_value:
                        normalized_item = str(item).strip()
                        if not normalized_item or normalized_item in seen:
                            continue
                        seen.add(normalized_item)
                        items.append(normalized_item)
                    normalized_params[key] = items
            out[normalized_name] = normalized_params
        return out

    @field_validator("numbering_scheme", mode="before")
    @classmethod
    def _normalize_numbering_scheme(cls, value):
        return str(value or "imgt").strip().lower()

    @field_validator("cdr_definition", mode="before")
    @classmethod
    def _normalize_cdr_definition(cls, value):
        if value is None:
            return None
        normalized = str(value).strip().lower()
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

        # checkpoint interval sanity
        if self.checkpoint_interval < 1:
            raise ValueError("checkpoint_interval must be at least 1")
        return self
