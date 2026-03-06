from __future__ import annotations

from biotite.sequence import ProteinSequence


def residue_code(res_name: str) -> str:
    try:
        return ProteinSequence.convert_letter_3to1(str(res_name))
    except Exception:
        return "X"


def chain_residue_entries(chain_arr) -> list[tuple[str, int, str]]:
    seen: set[tuple[str, int]] = set()
    entries: list[tuple[str, int, str]] = []
    chain_ids = chain_arr.chain_id.astype(str)
    for chain_id, res_id, res_name in zip(chain_ids, chain_arr.res_id, chain_arr.res_name.astype(str)):
        key = (chain_id, int(res_id))
        if key in seen:
            continue
        seen.add(key)
        entries.append((str(chain_id), int(res_id), residue_code(str(res_name))))
    return entries


def residue_sequence(chain_arr) -> str:
    return "".join(res_code for _chain_id, _res_id, res_code in chain_residue_entries(chain_arr))


def sequences_by_chain(arr) -> dict[str, str]:
    out: dict[str, str] = {}
    for chain_id in sorted({str(chain_id) for chain_id in arr.chain_id.astype(str)}):
        chain_arr = arr[arr.chain_id.astype(str) == chain_id]
        out[chain_id] = residue_sequence(chain_arr)
    return out
