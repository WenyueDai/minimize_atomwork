# minimum_atomworks Test Guide

This directory contains the automated test suite for `minimum_atomworks`.

The tests are written with Python `unittest` and are intended to be run from the
repository root:

```bash
cd /home/eva/minimum_atomworks
```

## 1. Which Python to use

Use the project environment that has the scientific dependencies installed:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python
```

If you use a different Python, imports such as `biotite`, `pandas`, `pyarrow`,
or `pydantic` may be missing and some tests may fail or be skipped.

## 2. Run the full suite

This is the main command to verify the package:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest discover -s minimum_atw/tests -v
```

What this does:

- `-m unittest discover` uses Python's built-in test discovery
- `-s minimum_atw/tests` tells discovery where the tests live
- `-v` prints each test name and result

Use this when:

- you changed package architecture
- you changed pipeline logic
- you changed plugin behavior
- you changed output-file naming or merge behavior
- you want a final confidence check before committing

## 3. Run a single test file

Use the module path form:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest minimum_atw.tests.test_integration_smoke -v
```

Other common examples:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest minimum_atw.tests.test_interface_contacts -v
```

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest minimum_atw.tests.test_dataset_merge -v
```

Use this when:

- you changed one subsystem
- you want faster feedback than the full suite
- you are debugging one failure area

## 4. Run one specific test method

Use the full dotted path:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest minimum_atw.tests.test_integration_smoke.IntegrationSmokeTests.test_identity_pipeline_writes_expected_tables -v
```

Example for interface-specific behavior:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest minimum_atw.tests.test_interface_contacts.InterfaceContactsTests.test_antibody_interface_rows_include_cdr_contact_fields -v
```

Use this when:

- you are iterating on one bug
- one exact regression needs to be confirmed repeatedly

## 5. Useful test groups

The files are organized roughly by subsystem:

- `test_config.py`
  config normalization and validation
- `test_tables.py`
  unified PDB parquet merge and identity-key behavior
- `test_registry.py`
  registry instantiation behavior
- `test_stage_buffer.py`
  buffered staging and spill-to-parquet behavior
- `test_dataset_merge.py`
  merge-datasets compatibility, metadata, and output-file resolution checks
- `test_dataset_analysis_runtime.py`
  dataset-analysis loading, projection, cleanup, summary behavior, and configured filename handling
- `test_interface_contacts.py`
  interface residue outputs and antibody/VHH CDR interface fields
- `test_antibody_numbering.py`
  antibody numbering scheme and CDR extraction behavior
- `test_cdr_entropy.py`
  CDR entropy selection behavior
- `test_integration_smoke.py`
  small end-to-end pipeline smoke test
- `test_package_init.py`
  lazy public package API behavior

## 6. Recommended workflow

### If you changed one plugin

Run the relevant targeted file first, then the full suite:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest minimum_atw.tests.test_interface_contacts -v
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest discover -s minimum_atw/tests -v
```

### If you changed core pipeline logic

Run the architecture-sensitive tests first:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest \
  minimum_atw.tests.test_tables \
  minimum_atw.tests.test_stage_buffer \
  minimum_atw.tests.test_dataset_merge \
  minimum_atw.tests.test_integration_smoke \
  -v
```

Then run the full suite:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest discover -s minimum_atw/tests -v
```

### If you changed dataset analyses

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest \
  minimum_atw.tests.test_dataset_analysis_runtime \
  minimum_atw.tests.test_cdr_entropy \
  -v
```

## 7. How to read failures

If a test fails:

1. Read the test name first.
2. Open the corresponding file in `minimum_atw/tests/`.
3. Check whether the failure is:
   - a schema change
   - a metadata change
   - an import path change
   - a plugin output change
   - a real correctness regression

Most tests use very small temporary datasets, so failures are usually fast to reproduce.

## 8. Common mistakes

### Running discovery from the wrong place

Wrong:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest discover -s tests -v
```

Correct:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest discover -s minimum_atw/tests -v
```

The test directory now lives under `minimum_atw/tests`, not top-level `tests`.

### Using a Python without dependencies

If you see errors like:

- `ModuleNotFoundError: No module named 'biotite'`
- `ModuleNotFoundError: No module named 'pyarrow'`
- `ModuleNotFoundError: No module named 'pydantic'`

use:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python
```

### Running from outside the repo root

Some module imports assume you run from:

```bash
cd /home/eva/minimum_atomworks
```

If you run elsewhere, `minimum_atw` module resolution may fail.

## 9. Quick copy-paste section

Full suite:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest discover -s minimum_atw/tests -v
```

One file:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest minimum_atw.tests.test_interface_contacts -v
```

One test:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest minimum_atw.tests.test_dataset_merge.DatasetMergeTests.test_merge_dataset_outputs_rejects_incompatible_runtime_config -v
```
