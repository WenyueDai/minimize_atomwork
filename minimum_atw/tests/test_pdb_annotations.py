from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    from biotite.structure.io import load_structure

    from minimum_atw.core.config import Config
    from minimum_atw.plugins.base import Context
    from minimum_atw.plugins.pdb.annotations import (
        chain_unique_residue_count,
        role_residue_entries,
        role_sequences_by_chain,
    )
    from minimum_atw.plugins.pdb.interface_annotations import interface_contact_summary_for_roles
except ModuleNotFoundError as exc:
    if exc.name not in {"biotite", "numpy", "pydantic"}:
        raise
    load_structure = None
    Config = None
    Context = None


@unittest.skipIf(load_structure is None or Config is None, "PDB annotation dependencies are not installed")
class PdbAnnotationsTests(unittest.TestCase):
    def _load_structure(self, pdb_text: str):
        with tempfile.TemporaryDirectory(prefix="minimum_atw_pdb_annotations_") as tmp_dir:
            path = Path(tmp_dir) / "toy.pdb"
            path.write_text(textwrap.dedent(pdb_text))
            return load_structure(path)

    def _make_context(self, arr) -> Context:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            roles={"binder": ["A"]},
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

    def test_role_annotations_are_cached_and_reset_when_views_rebuild(self) -> None:
        arr_one = self._load_structure(
            """\
            ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
            ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
            ATOM      3  N   TYR A   2       3.000   0.000   0.000  1.00 20.00           N
            TER
            END
            """
        )
        ctx = self._make_context(arr_one)

        seq_by_chain = role_sequences_by_chain(ctx, "binder")
        seq_by_chain_again = role_sequences_by_chain(ctx, "binder")

        self.assertIs(seq_by_chain, seq_by_chain_again)
        self.assertEqual(seq_by_chain, {"A": "GY"})
        self.assertEqual(role_residue_entries(ctx, "binder"), [("A", 1, "G"), ("A", 2, "Y")])
        self.assertEqual(chain_unique_residue_count(ctx, "A"), 2)

        arr_two = self._load_structure(
            """\
            ATOM      1  N   ALA A   8       0.000   0.000   0.000  1.00 20.00           N
            ATOM      2  CA  ALA A   8       1.200   0.000   0.000  1.00 20.00           C
            TER
            END
            """
        )
        ctx.aa = arr_two
        ctx.rebuild_views()

        self.assertEqual(role_sequences_by_chain(ctx, "binder"), {"A": "A"})
        self.assertEqual(role_residue_entries(ctx, "binder"), [("A", 8, "A")])
        self.assertEqual(chain_unique_residue_count(ctx, "A"), 1)

    def test_interface_summary_is_cached_and_reset_when_views_rebuild(self) -> None:
        arr = self._load_structure(
            """\
            ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
            ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
            ATOM      3  N   ALA B   2       0.000   0.000   3.000  1.00 20.00           N
            ATOM      4  CA  ALA B   2       1.200   0.000   3.000  1.00 20.00           C
            TER
            END
            """
        )
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            roles={"binder": ["A"], "target": ["B"]},
            interface_pairs=[("binder", "target")],
            contact_distance=5.0,
        )
        ctx = Context(
            path="/tmp/source.pdb",
            assembly_id="1",
            aa=arr,
            role_map={role: tuple(chains) for role, chains in cfg.roles.items()},
            config=cfg,
        )
        ctx.rebuild_views()

        summary = interface_contact_summary_for_roles(
            ctx,
            left_role="binder",
            right_role="target",
            contact_distance=5.0,
        )
        summary_again = interface_contact_summary_for_roles(
            ctx,
            left_role="binder",
            right_role="target",
            contact_distance=5.0,
        )

        self.assertIs(summary, summary_again)
        assert summary is not None
        self.assertEqual(summary["left_interface_residues"], [("A", 1, "G")])
        self.assertEqual(summary["right_interface_residues"], [("B", 2, "A")])

        far = self._load_structure(
            """\
            ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N
            ATOM      2  CA  GLY A   1       1.200   0.000   0.000  1.00 20.00           C
            ATOM      3  N   ALA B   2      30.000   0.000   3.000  1.00 20.00           N
            ATOM      4  CA  ALA B   2      31.200   0.000   3.000  1.00 20.00           C
            TER
            END
            """
        )
        ctx.aa = far
        ctx.rebuild_views()

        self.assertIsNone(
            interface_contact_summary_for_roles(
                ctx,
                left_role="binder",
                right_role="target",
                contact_distance=5.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
