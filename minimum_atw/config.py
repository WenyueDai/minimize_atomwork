from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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
    dataset_analysis: bool = False
    dataset_analyses: list[str] = Field(default_factory=list)
    dataset_annotations: dict[str, str] = Field(default_factory=dict)
    numbering_roles: list[str] = Field(default_factory=list)
