from __future__ import annotations

from biotite.sequence import ProteinSequence


def residue_sequence(chain_arr) -> str:
    seen: set[tuple[str, int]] = set()
    tokens: list[str] = []
    chain_ids = chain_arr.chain_id.astype(str)
    for chain_id, res_id, res_name in zip(chain_ids, chain_arr.res_id, chain_arr.res_name.astype(str)):
        key = (chain_id, int(res_id))
        if key in seen:
            continue
        seen.add(key)
        try:
            tokens.append(ProteinSequence.convert_letter_3to1(str(res_name)))
        except Exception:
            tokens.append("X")
    return "".join(tokens)


def sequences_by_chain(arr) -> dict[str, str]:
    out: dict[str, str] = {}
    for chain_id in sorted({str(chain_id) for chain_id in arr.chain_id.astype(str)}):
        chain_arr = arr[arr.chain_id.astype(str) == chain_id]
        out[chain_id] = residue_sequence(chain_arr)
    return out
