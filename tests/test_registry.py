from __future__ import annotations

import unittest

from minimum_atw.core.registry import instantiate_unit


class _DummyUnit:
    def __init__(self) -> None:
        self.values: list[str] = []


class RegistryTests(unittest.TestCase):
    def test_instantiate_unit_returns_fresh_instance(self) -> None:
        unit = _DummyUnit()
        unit.values.append("seen")

        fresh = instantiate_unit(unit)

        self.assertIsInstance(fresh, _DummyUnit)
        self.assertIsNot(fresh, unit)
        self.assertEqual(fresh.values, [])


if __name__ == "__main__":
    unittest.main()
