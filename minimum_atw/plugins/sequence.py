from __future__ import annotations

from .interface_analysis.interface_metrics import chain_residue_entries, residue_code


def residue_sequence(chain_arr) -> str:
    return "".join(res_code for _chain_id, _res_id, res_code in chain_residue_entries(chain_arr))


def sequences_by_chain(arr) -> dict[str, str]:
    out: dict[str, str] = {}
    for chain_id in sorted({str(chain_id) for chain_id in arr.chain_id.astype(str)}):
        chain_arr = arr[arr.chain_id.astype(str) == chain_id]
        out[chain_id] = residue_sequence(chain_arr)
    return out
