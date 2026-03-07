from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from minimum_atw.core.pipeline import merge_dataset_outputs
from minimum_atw.core.tables import BAD_COLS, PDB_KEY_COLS, PDB_TABLE_NAME, STATUS_COLS
from minimum_atw.tests.helpers import read_pdb_grain


def _write_source_dataset(
    out_dir: Path,
    *,
    path_value: str,
    merge_compatibility: dict,
    structures_extra: dict | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    base_rows = [
        {"path": path_value, "assembly_id": "1", "grain": "structure", "chain_id": "", "role": "", "pair": "", "role_left": "", "role_right": ""},
        {"path": path_value, "assembly_id": "1", "grain": "chain", "chain_id": "A", "role": "", "pair": "", "role_left": "", "role_right": ""},
        {"path": path_value, "assembly_id": "1", "grain": "role", "chain_id": "", "role": "binder", "pair": "", "role_left": "", "role_right": ""},
        {
            "path": path_value,
            "assembly_id": "1",
            "grain": "interface",
            "chain_id": "",
            "role": "",
            "pair": "binder__target",
            "role_left": "binder",
            "role_right": "target",
        },
    ]
    if structures_extra:
        base_rows[0].update(structures_extra)

    frame = pd.DataFrame(base_rows)
    ordered = [col for col in PDB_KEY_COLS if col in frame.columns]
    ordered.extend(col for col in frame.columns if col not in ordered)
    frame = frame.loc[:, ordered]
    frame.to_parquet(out_dir / f"{PDB_TABLE_NAME}.parquet", index=False)
    table_columns = {PDB_TABLE_NAME: list(frame.columns)}

    pd.DataFrame(
        [{"path": path_value, "assembly_id": "1", "plugin": "identity", "status": "ok", "message": "rows=1"}],
        columns=STATUS_COLS,
    ).to_parquet(out_dir / "plugin_status.parquet", index=False)
    pd.DataFrame(columns=BAD_COLS).to_parquet(out_dir / "bad_files.parquet", index=False)

    (out_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "output_kind": "run",
                "config": {
                    "input_dir": "/tmp/input",
                    "out_dir": str(out_dir),
                    **merge_compatibility,
                },
                "counts": {"structures": 1, "chains": 1, "roles": 1, "interfaces": 1, "status": 1, "bad": 0},
                "merge_compatibility": merge_compatibility,
                "table_columns": table_columns,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


class DatasetMergeTests(unittest.TestCase):
    def test_merge_dataset_outputs_writes_compatibility_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_merge_") as tmp_dir:
            root = Path(tmp_dir)
            source_one = root / "source_one"
            source_two = root / "source_two"
            merged_out = root / "merged"
            compatibility = {
                "assembly_id": "1",
                "roles": {"binder": ["A"], "target": ["B"]},
                "interface_pairs": [["binder", "target"]],
                "plugins": ["identity"],
                "manipulations": [],
                "contact_distance": 5.0,
                "rosetta_executable": None,
                "rosetta_database": None,
                "superimpose_reference_path": None,
                "superimpose_on_chains": [],
                "numbering_roles": [],
                "numbering_scheme": "imgt",
                "cdr_definition": None,
            }
            _write_source_dataset(
                source_one,
                path_value="/tmp/source_one.pdb",
                merge_compatibility=compatibility,
                structures_extra={"id__n_atoms_total": 10},
            )
            _write_source_dataset(
                source_two,
                path_value="/tmp/source_two.pdb",
                merge_compatibility=compatibility,
                structures_extra={"id__n_atoms_total": 11},
            )

            counts = merge_dataset_outputs([source_one, source_two], merged_out)

            metadata = json.loads((merged_out / "dataset_metadata.json").read_text())
            structures = read_pdb_grain(merged_out, "structure")

            self.assertEqual(counts["structures"], 2)
            self.assertEqual(len(structures), 2)
            self.assertEqual(metadata["output_kind"], "merged_dataset")
            self.assertEqual(metadata["counts"]["status"], 2)
            self.assertEqual(metadata["status_summary"], {"ok": 2})
            self.assertEqual(metadata["merge_compatibility"], compatibility)
            self.assertEqual(
                metadata["table_columns"]["pdb"],
                ["path", "assembly_id", "grain", "chain_id", "role", "pair", "role_left", "role_right", "id__n_atoms_total", "sub_id"],
            )
            self.assertEqual(metadata["source_outputs"][0]["output_kind"], "run")
            self.assertFalse((merged_out / "plugin_status.parquet").exists())

    def test_merge_dataset_outputs_rejects_incompatible_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimum_atw_merge_") as tmp_dir:
            root = Path(tmp_dir)
            source_one = root / "source_one"
            source_two = root / "source_two"
            merged_out = root / "merged"
            compatibility = {
                "assembly_id": "1",
                "roles": {"binder": ["A"], "target": ["B"]},
                "interface_pairs": [["binder", "target"]],
                "plugins": ["identity"],
                "manipulations": [],
                "contact_distance": 5.0,
                "rosetta_executable": None,
                "rosetta_database": None,
                "superimpose_reference_path": None,
                "superimpose_on_chains": [],
                "numbering_roles": [],
                "numbering_scheme": "imgt",
                "cdr_definition": None,
            }
            incompatible = dict(compatibility)
            incompatible["contact_distance"] = 6.0

            _write_source_dataset(source_one, path_value="/tmp/source_one.pdb", merge_compatibility=compatibility)
            _write_source_dataset(source_two, path_value="/tmp/source_two.pdb", merge_compatibility=incompatible)

            import warnings
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                merge_dataset_outputs([source_one, source_two], merged_out)
            self.assertTrue(any("Incompatible source runtime configuration" in str(warning.message) for warning in w))


if __name__ == "__main__":
    unittest.main()
