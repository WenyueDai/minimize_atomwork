from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=512)
def _cached_cdr_sequences(
    sequence: str,
    scheme: str,
    cdr_definition: str | None,
) -> tuple[str, str, str]:
    try:
        from abnumber import Chain
    except ImportError as exc:
        raise RuntimeError("abnumber is required for antibody CDR numbering") from exc

    chain_kwargs = {
        "scheme": scheme,
        "cdr_definition": cdr_definition,
        "use_anarcii": True,
    }
    try:
        numbered = Chain(sequence, **chain_kwargs)
    except Exception as exc:
        raise RuntimeError(
            f"abnumber failed to number sequence with scheme={scheme!r}, cdr_definition={cdr_definition!r}: {exc}"
        ) from exc

    return (
        str(getattr(numbered, "cdr1_seq", "") or ""),
        str(getattr(numbered, "cdr2_seq", "") or ""),
        str(getattr(numbered, "cdr3_seq", "") or ""),
    )


@lru_cache(maxsize=512)
def _cached_cdr_region_labels(
    sequence: str,
    scheme: str,
    cdr_definition: str | None,
) -> tuple[str, ...]:
    try:
        from abnumber import Chain
    except ImportError as exc:
        raise RuntimeError("abnumber is required for antibody CDR numbering") from exc

    chain_kwargs = {
        "scheme": scheme,
        "cdr_definition": cdr_definition,
        "use_anarcii": True,
    }
    try:
        numbered = Chain(sequence, **chain_kwargs)
    except Exception as exc:
        raise RuntimeError(
            f"abnumber failed to number sequence with scheme={scheme!r}, cdr_definition={cdr_definition!r}: {exc}"
        ) from exc

    labels: list[str] = []
    for pos, _aa in numbered:
        region = str(pos.get_region()).strip().lower()
        labels.append(region if region.startswith("cdr") else "")
    if len(labels) > len(sequence):
        raise RuntimeError(
            f"abnumber returned {len(labels)} numbered positions for a sequence of length {len(sequence)}"
        )
    if len(labels) < len(sequence):
        labels.extend([""] * (len(sequence) - len(labels)))
    return tuple(labels)


def cdr_sequences(
    sequence: str,
    *,
    scheme: str = "imgt",
    cdr_definition: str | None = None,
) -> dict[str, str]:
    cdr1, cdr2, cdr3 = _cached_cdr_sequences(sequence, scheme, cdr_definition)
    return {
        "cdr1": cdr1,
        "cdr2": cdr2,
        "cdr3": cdr3,
    }


def cdr_lengths(
    sequence: str,
    *,
    scheme: str = "imgt",
    cdr_definition: str | None = None,
) -> dict[str, int]:
    seqs = cdr_sequences(sequence, scheme=scheme, cdr_definition=cdr_definition)
    return {key: len(value) for key, value in seqs.items()}


def cdr_indices(
    sequence: str,
    *,
    scheme: str = "imgt",
    cdr_definition: str | None = None,
) -> dict[str, list[int]]:
    labels = _cached_cdr_region_labels(sequence, scheme, cdr_definition)
    return {
        cdr_name: [idx for idx, label in enumerate(labels) if label == cdr_name]
        for cdr_name in ("cdr1", "cdr2", "cdr3")
    }
