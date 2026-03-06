from __future__ import annotations

import unittest
from unittest.mock import patch

from minimum_atw.plugins.antibody_analysis import antibody_numbering
from minimum_atw.plugins.antibody_analysis.antibody_numbering import cdr_lengths, cdr_sequences


class _FakeChain:
    def __init__(self, sequence: str, **kwargs) -> None:
        self.sequence = sequence
        self.kwargs = kwargs
        self.cdr1_seq = "AAA"
        self.cdr2_seq = "BBBB"
        self.cdr3_seq = "CC"


class AntibodyNumberingTests(unittest.TestCase):
    @patch("abnumber.Chain", new=_FakeChain)
    def test_cdr_sequences_passes_scheme_and_cdr_definition(self) -> None:
        seqs = cdr_sequences("EVQL", scheme="kabat", cdr_definition="north")

        self.assertEqual(seqs, {"cdr1": "AAA", "cdr2": "BBBB", "cdr3": "CC"})

    @patch("abnumber.Chain", new=_FakeChain)
    def test_cdr_lengths_uses_returned_sequences(self) -> None:
        lengths = cdr_lengths("EVQL", scheme="imgt", cdr_definition=None)

        self.assertEqual(lengths, {"cdr1": 3, "cdr2": 4, "cdr3": 2})

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
