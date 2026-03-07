from __future__ import annotations

from .antibody_analysis import AntibodyCDRLengthsPlugin, AntibodyCDRSequencesPlugin
from .interface_analysis.interface_contacts import InterfaceContactsPlugin
from .interface_analysis.rosetta_interface import RosettaInterfaceExamplePlugin
from .structure_analysis import ChainStatsPlugin, IdentityPlugin, RoleSequencesPlugin, RoleStatsPlugin
from ..core.registry import load_registry


def _builtin_plugins() -> dict[str, object]:
    return {
        "antibody_cdr_lengths": AntibodyCDRLengthsPlugin(),
        "antibody_cdr_sequences": AntibodyCDRSequencesPlugin(),
        "chain_stats": ChainStatsPlugin(),
        "identity": IdentityPlugin(),
        "interface_contacts": InterfaceContactsPlugin(),
        "role_sequences": RoleSequencesPlugin(),
        "role_stats": RoleStatsPlugin(),
        "rosetta_interface_example": RosettaInterfaceExamplePlugin(),
    }


PLUGIN_REGISTRY = load_registry(
    builtin_items=_builtin_plugins(),
    entry_point_group="minimum_atw.plugins",
    label="plugin",
    require_prefix=True,
)

__all__ = [
    "AntibodyCDRLengthsPlugin",
    "AntibodyCDRSequencesPlugin",
    "ChainStatsPlugin",
    "IdentityPlugin",
    "InterfaceContactsPlugin",
    "PLUGIN_REGISTRY",
    "RoleSequencesPlugin",
    "RoleStatsPlugin",
    "RosettaInterfaceExamplePlugin",
]
