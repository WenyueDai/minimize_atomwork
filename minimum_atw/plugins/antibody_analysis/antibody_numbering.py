from __future__ import annotations

from ..sequence import residue_sequence


def imgt_cdr_sequences(sequence: str) -> dict[str, str]:
    try:
        from abnumber import Chain
    except ImportError as exc:
        raise RuntimeError("abnumber is required for antibody CDR numbering") from exc

    try:
        numbered = Chain(sequence, scheme="imgt", use_anarcii=True)
    except Exception as exc:
        raise RuntimeError(f"abnumber failed to number sequence: {exc}") from exc

    out = {"cdr1": "", "cdr2": "", "cdr3": ""}
    for pos, aa in numbered:
        region = str(pos.get_region()).upper()
        if region.startswith("CDR"):
            key = region.lower()
            if key in out:
                out[key] += str(aa)
    return out


def imgt_cdr_lengths(sequence: str) -> dict[str, int]:
    seqs = imgt_cdr_sequences(sequence)
    return {key: len(value) for key, value in seqs.items()}
