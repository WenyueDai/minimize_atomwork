from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
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
    dataset_analyses: list[str] = Field(default_factory=list)
    dataset_annotations: dict[str, str] = Field(default_factory=dict)
    numbering_roles: list[str] = Field(default_factory=list)

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
