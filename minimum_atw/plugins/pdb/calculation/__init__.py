from __future__ import annotations

from .antibody_analysis import AntibodyCDRSequencesPlugin
from .interface_analysis.abepitope_score import AbEpiTopeScorePlugin
from .interface_analysis.dockq_score import DockQPlugin
from .interface_analysis.interface_contacts import InterfaceContactsPlugin
from .interface_analysis.interface_residue_metrics import InterfaceMetricsPlugin
from .interface_analysis.pdockq_score import PdockQPlugin
from .interface_analysis.rosetta_interface import RosettaInterfaceExamplePlugin
from .structure_analysis import AbLang2ScorePlugin, ChainStatsPlugin, EsmIf1ScorePlugin, IdentityPlugin, RoleSequencesPlugin, RoleStatsPlugin, SuperimposePlugin
from ....core.registry import load_registry


def _builtin_pdb_calculations() -> dict[str, object]:
    return {
        "ablang2_score": AbLang2ScorePlugin(),
        "abepitope_score": AbEpiTopeScorePlugin(),
        "antibody_cdr_sequences": AntibodyCDRSequencesPlugin(),
        "chain_stats": ChainStatsPlugin(),
        "dockq_score": DockQPlugin(),
        "esm_if1_score": EsmIf1ScorePlugin(),
        "identity": IdentityPlugin(),
        "interface_contacts": InterfaceContactsPlugin(),
        "interface_metrics": InterfaceMetricsPlugin(),
        "pdockq_score": PdockQPlugin(),
        "role_sequences": RoleSequencesPlugin(),
        "role_stats": RoleStatsPlugin(),
        "rosetta_interface_example": RosettaInterfaceExamplePlugin(),
        "structure_rmsd": SuperimposePlugin(),
    }


PDB_CALCULATION_REGISTRY = load_registry(
    builtin_items=_builtin_pdb_calculations(),
    entry_point_group="minimum_atw.plugins",
    label="pdb_calculation",
    require_prefix=True,
)

__all__ = [
    "AbLang2ScorePlugin",
    "AbEpiTopeScorePlugin",
    "AntibodyCDRSequencesPlugin",
    "ChainStatsPlugin",
    "DockQPlugin",
    "EsmIf1ScorePlugin",
    "IdentityPlugin",
    "InterfaceContactsPlugin",
    "InterfaceMetricsPlugin",
    "PDB_CALCULATION_REGISTRY",
    "PdockQPlugin",
    "RoleSequencesPlugin",
    "RoleStatsPlugin",
    "RosettaInterfaceExamplePlugin",
    "SuperimposePlugin",
]
