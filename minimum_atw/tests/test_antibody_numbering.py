from __future__ import annotations

import unittest
from unittest.mock import patch

from minimum_atw.plugins.pdb.calculation.antibody_analysis import antibody_numbering
from minimum_atw.plugins.pdb.calculation.antibody_analysis.antibody_numbering import (
    cdr_lengths,
    cdr_position_labels,
    cdr_sequences,
)


class _FakePosition:
    def __init__(self, label: str, region: str) -> None:
        self.label = label
        self.region = region

    def get_region(self) -> str:
        return self.region

    def __str__(self) -> str:
        return self.label


class _FakeChain:
    def __init__(self, sequence: str, **kwargs) -> None:
        self.sequence = sequence
        self.kwargs = kwargs
        self.cdr1_seq = "AAA"
        self.cdr2_seq = "BBBB"
        self.cdr3_seq = "CC"

    def __iter__(self):
        yield _FakePosition("H27", "cdr1"), "A"
        yield _FakePosition("H28", "cdr1"), "A"
        yield _FakePosition("H56", "cdr2"), "B"
        yield _FakePosition("H57", "cdr2"), "B"
        yield _FakePosition("H105", "cdr3"), "C"
        yield _FakePosition("H106", "cdr3"), "C"


class AntibodyNumberingTests(unittest.TestCase):
    @patch("abnumber.Chain", new=_FakeChain)
    def test_cdr_sequences_passes_scheme_and_cdr_definition(self) -> None:
        seqs = cdr_sequences("EVQL", scheme="kabat", cdr_definition="north")

        self.assertEqual(seqs, {"cdr1": "AAA", "cdr2": "BBBB", "cdr3": "CC"})

    @patch("abnumber.Chain", new=_FakeChain)
    def test_cdr_lengths_uses_returned_sequences(self) -> None:
        lengths = cdr_lengths("EVQL", scheme="imgt", cdr_definition=None)

        self.assertEqual(lengths, {"cdr1": 3, "cdr2": 4, "cdr3": 2})

    @patch("abnumber.Chain", new=_FakeChain)
    def test_cdr_position_labels_follow_numbered_positions(self) -> None:
        labels = cdr_position_labels("EVQL", scheme="imgt", cdr_definition=None)

        self.assertEqual(
            labels,
            {
                "cdr1": ("H27", "H28"),
                "cdr2": ("H56", "H57"),
                "cdr3": ("H105", "H106"),
            },
        )

    def test_cdr_sequences_caches_identical_requests(self) -> None:
        calls: list[tuple[str, str, str | None]] = []

        class CountingChain(_FakeChain):
            def __init__(self, sequence: str, **kwargs) -> None:
                super().__init__(sequence, **kwargs)
                calls.append((sequence, kwargs.get("scheme"), kwargs.get("cdr_definition")))

        antibody_numbering._cached_cdr_sequences.cache_clear()
        with patch("abnumber.Chain", new=CountingChain):
            first = cdr_sequences("EVQL", scheme="imgt", cdr_definition="imgt")
            second = cdr_sequences("EVQL", scheme="imgt", cdr_definition="imgt")

        self.assertEqual(first, second)
        self.assertEqual(calls, [("EVQL", "imgt", "imgt")])


if __name__ == "__main__":
    unittest.main()
