from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    from biotite.structure.io import load_structure
    from minimum_atw.core.config import Config
    from minimum_atw.plugins.base import Context
    from minimum_atw.plugins.pdb.quality_control.structure_clashes import StructureClashesManipulation
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "numpy", "pydantic"}:
        raise
    load_structure = None
    Config = None
    Context = None
    StructureClashesManipulation = None


@unittest.skipIf(load_structure is None or Config is None, "quality control dependencies are not installed")
class StructureClashesTests(unittest.TestCase):
    def _make_context(self, pdb_text: str, **config_overrides):
        with tempfile.TemporaryDirectory(prefix="minimum_atw_clash_test_") as tmp_dir:
            path = Path(tmp_dir) / "toy.pdb"
            path.write_text(textwrap.dedent(pdb_text))
            arr = load_structure(path)

        cfg_kwargs = {
            "input_dir": "/tmp/in",
            "out_dir": "/tmp/out",
            "roles": {"binder": ["A"], "target": ["B"]},
            "interface_pairs": [("binder", "target")],
        }
        cfg_kwargs.update(config_overrides)
        cfg = Config(**cfg_kwargs)
        ctx = Context(
            path="/tmp/source.pdb",
            assembly_id="1",
            aa=arr,
            role_map={role: tuple(chains) for role, chains in cfg.roles.items()},
            config=cfg,
        )
        ctx.rebuild_views()
        return ctx

    def test_strict_cutoff_flags_nonlocal_pairs_below_two_angstrom(self) -> None:
        ctx = self._make_context(
            """\
            ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
            ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
            ATOM      3  N   GLY A   3       1.500   0.000   0.000  1.00 20.00           N
            ATOM      4  CA  GLY A   3       2.700   0.000   0.000  1.00 20.00           C
            ATOM      5  N   ALA B   1      10.000   0.000   0.000  1.00 20.00           N
            TER
            END
            """
        )

        rows = list(StructureClashesManipulation().run(ctx))

        self.assertEqual(len(rows), 1)
        self.assertTrue(bool(rows[0]["has_clash"]))
        self.assertGreaterEqual(int(rows[0]["n_clashing_atom_pairs"]), 1)

    def test_inter_chain_scope_ignores_same_chain_clashes(self) -> None:
        ctx = self._make_context(
            """\
            ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
            ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
            ATOM      3  N   GLY A   3       1.500   0.000   0.000  1.00 20.00           N
            ATOM      4  CA  GLY A   3       2.700   0.000   0.000  1.00 20.00           C
            ATOM      5  N   ALA B   1      10.000   0.000   0.000  1.00 20.00           N
            TER
            END
            """,
            clash_scope="inter_chain",
        )

        rows = list(StructureClashesManipulation().run(ctx))

        self.assertEqual(len(rows), 1)
        self.assertFalse(bool(rows[0]["has_clash"]))
        self.assertEqual(int(rows[0]["n_clashing_atom_pairs"]), 0)

    def test_interface_only_scope_counts_only_configured_role_pairs(self) -> None:
        ctx = self._make_context(
            """\
            ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
            ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
            ATOM      3  N   GLY B   1       1.500   0.000   0.000  1.00 20.00           N
            ATOM      4  CA  GLY B   1       2.700   0.000   0.000  1.00 20.00           C
            ATOM      5  N   GLY C   1       0.900   0.000   0.000  1.00 20.00           N
            TER
            END
            """,
            roles={"binder": ["A"], "target": ["B"], "off_target": ["C"]},
            interface_pairs=[("binder", "target")],
            clash_scope="interface_only",
        )

        rows = list(StructureClashesManipulation().run(ctx))

        self.assertEqual(len(rows), 1)
        self.assertTrue(bool(rows[0]["has_clash"]))
        self.assertEqual(int(rows[0]["n_clashing_atom_pairs"]), 3)
        self.assertEqual(int(rows[0]["n_clashing_atoms"]), 4)


if __name__ == "__main__":
    unittest.main()
