from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    import biotite.structure as struc
    from biotite.structure.io import load_structure

    from minimum_atw.core.config import Config
    from minimum_atw.plugins.base import Context
    from minimum_atw.plugins.pdb.calculation.structure_analysis.chain_stats import ChainStatsPlugin
    from minimum_atw.plugins.pdb.calculation.structure_analysis.role_stats import RoleStatsPlugin
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "numpy", "pydantic"}:
        raise
    struc = None
    load_structure = None
    Config = None
    Context = None
    ChainStatsPlugin = None
    RoleStatsPlugin = None


@unittest.skipIf(load_structure is None or Config is None, "structure stat dependencies are not installed")
class StructureStatsTests(unittest.TestCase):
    def _make_context(self, pdb_text: str) -> Context:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_structure_stats_") as tmp_dir:
            path = Path(tmp_dir) / "toy.pdb"
            path.write_text(textwrap.dedent(pdb_text))
            arr = load_structure(path)

        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            roles={"binder": ["A", "B"], "chain_a_only": ["A"]},
            interface_pairs=[],
        )
        ctx = Context(
            path="/tmp/source.pdb",
            assembly_id="1",
            aa=arr,
            role_map={role: tuple(chains) for role, chains in cfg.roles.items()},
            config=cfg,
        )
        ctx.rebuild_views()
        return ctx

    def test_chain_stats_uses_biotite_gyration_radius(self) -> None:
        ctx = self._make_context(
            """\
            ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
            ATOM      2  CA  GLY A   1       2.000   0.000   0.000  1.00 20.00           C
            ATOM      3  C   GLY A   1       2.000   2.000   0.000  1.00 20.00           C
            ATOM      4  N   ALA B   1      20.000   0.000   0.000  1.00 20.00           N
            ATOM      5  CA  ALA B   1      22.000   0.000   0.000  1.00 20.00           C
            TER
            END
            """
        )

        rows = list(ChainStatsPlugin().run(ctx))
        row_by_chain = {row["chain_id"]: row for row in rows}

        self.assertIn("A", row_by_chain)
        expected = float(struc.gyration_radius(ctx.chains["A"]))
        observed = float(row_by_chain["A"]["radius_of_gyration"])
        self.assertAlmostEqual(observed, expected, places=6)

    def test_role_stats_uses_biotite_gyration_radius(self) -> None:
        ctx = self._make_context(
            """\
            ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
            ATOM      2  CA  GLY A   1       2.000   0.000   0.000  1.00 20.00           C
            ATOM      3  C   GLY A   1       2.000   2.000   0.000  1.00 20.00           C
            ATOM      4  N   ALA B   1      20.000   0.000   0.000  1.00 20.00           N
            ATOM      5  CA  ALA B   1      22.000   0.000   0.000  1.00 20.00           C
            TER
            END
            """
        )

        rows = list(RoleStatsPlugin().run(ctx))
        row_by_role = {row["role"]: row for row in rows}

        self.assertIn("binder", row_by_role)
        expected = float(struc.gyration_radius(ctx.roles["binder"]))
        observed = float(row_by_role["binder"]["radius_of_gyration"])
        self.assertAlmostEqual(observed, expected, places=6)


if __name__ == "__main__":
    unittest.main()
