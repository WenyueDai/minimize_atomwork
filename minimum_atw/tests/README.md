# minimum_atomworks Test Guide

This directory contains the automated test suite for `minimum_atomworks`.

All commands below assume you are in the **repository root** (the folder that
contains `pyproject.toml`).

## 1. Run the full suite

```bash
cd /path/to/minimum_atomworks   # repo root
pytest -v
```

`pytest` is included in the `[dev]` extra (`pip install -e ".[dev]"`).
It automatically discovers all `test_*.py` files under `minimum_atw/tests/`.

Alternative using the built-in `unittest` runner (no extra install needed):

```bash
python -m unittest discover -s minimum_atw/tests -v
```

## 2. Run a single test file

```bash
pytest minimum_atw/tests/test_integration_smoke.py -v
```

Or with unittest:

```bash
python -m unittest minimum_atw.tests.test_integration_smoke -v
```

## 3. Run one specific test method

```bash
pytest minimum_atw/tests/test_integration_smoke.py::IntegrationSmokeTests::test_identity_pipeline_writes_expected_tables -v
```

## 4. Test files by subsystem

| File | What it covers |
|---|---|
| `test_config.py` | config normalisation and validation |
| `test_tables.py` | unified PDB parquet merge and identity-key behaviour |
| `test_registry.py` | registry instantiation |
| `test_dataset_merge.py` | merge-datasets compatibility and output-file resolution |
| `test_dataset_analysis_runtime.py` | dataset-analysis loading, projection, summary |
| `test_interface_contacts.py` | interface residue outputs and CDR interface fields |
| `test_antibody_numbering.py` | antibody numbering scheme and CDR extraction |
| `test_cdr_entropy.py` | CDR entropy selection |
| `test_integration_smoke.py` | small end-to-end pipeline smoke test |
| `test_superimpose_features.py` | superimpose plugin and pre-aligned path |
| `test_abepitope_plugin.py` | AbEpiTope plugin availability and chain-hint logic |
| `test_rosetta_interface.py` | Rosetta plugin availability and config resolution |
| `test_plugin_execution.py` | plugin scheduling and execution machinery |
| `test_prepare_sections.py` | prepare phase section ordering |
| `test_extensions.py` | extension/plugin discovery |
| `test_package_init.py` | lazy public package API |

## 5. How to read failures

1. Read the test name — it usually describes the expected behaviour.
2. Open the corresponding file in `minimum_atw/tests/`.
3. Check whether the failure is a schema change, an import path change, a
   plugin output change, or a real correctness regression.

Most tests use small temporary datasets and run in seconds.

## 6. Common mistakes

**Wrong working directory** — always run from the repo root:

```bash
# Wrong
python -m unittest discover -s tests -v

# Correct
cd /path/to/minimum_atomworks
python -m unittest discover -s minimum_atw/tests -v
```

**Missing dependencies** — if you see `ModuleNotFoundError: No module named 'biotite'`
(or pandas, pyarrow, pydantic), your active Python environment is missing the
core install.  Run `pip install -e ".[dev]"` first.
