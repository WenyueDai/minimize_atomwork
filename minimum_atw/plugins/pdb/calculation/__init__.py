from __future__ import annotations

from .antibody_analysis import AntibodyCDRLengthsPlugin, AntibodyCDRSequencesPlugin
from .interface_analysis.abepitope_score import AbEpiTopeScorePlugin
from .interface_analysis.interface_contacts import InterfaceContactsPlugin
from .interface_analysis.interface_residue_metrics import InterfaceMetricsPlugin
from .interface_analysis.rosetta_interface import RosettaInterfaceExamplePlugin
from .structure_analysis import ChainStatsPlugin, IdentityPlugin, RoleSequencesPlugin, RoleStatsPlugin, SuperimposePlugin
from ....core.registry import load_registry


def _builtin_pdb_calculations() -> dict[str, object]:
    return {
        "abepitope_score": AbEpiTopeScorePlugin(),
        "antibody_cdr_lengths": AntibodyCDRLengthsPlugin(),
        "antibody_cdr_sequences": AntibodyCDRSequencesPlugin(),
        "chain_stats": ChainStatsPlugin(),
        "identity": IdentityPlugin(),
        "interface_contacts": InterfaceContactsPlugin(),
        "interface_metrics": InterfaceMetricsPlugin(),
        "role_sequences": RoleSequencesPlugin(),
        "role_stats": RoleStatsPlugin(),
        "rosetta_interface_example": RosettaInterfaceExamplePlugin(),
        "superimpose_homology": SuperimposePlugin(),
    }


PDB_CALCULATION_REGISTRY = load_registry(
    builtin_items=_builtin_pdb_calculations(),
    entry_point_group="minimum_atw.plugins",
    label="pdb_calculation",
    require_prefix=True,
)

__all__ = [
    "AbEpiTopeScorePlugin",
    "AntibodyCDRLengthsPlugin",
    "AntibodyCDRSequencesPlugin",
    "ChainStatsPlugin",
    "IdentityPlugin",
    "InterfaceContactsPlugin",
    "InterfaceMetricsPlugin",
    "PDB_CALCULATION_REGISTRY",
    "RoleSequencesPlugin",
    "RoleStatsPlugin",
    "RosettaInterfaceExamplePlugin",
    "SuperimposePlugin",
]
