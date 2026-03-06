# minimum_atomworks

`minimum_atomworks` is a structural data-processing package for large collections
of protein complexes.

It is built around four normalized tables:

- `structures`
- `chains`
- `roles`
- `interfaces`

The package is intended for:

- antibody-antigen complexes
- VHH or nanobody binders
- generic protein-protein complexes

Its design goals are:

- simple architecture
- normalized tabular outputs
- plugin-based extensibility
- minimal unnecessary intermediate files
- clear data flow
- scalability to large datasets

## Architecture

The runtime has four stages:

1. `prepare`
   load raw `.pdb` or `.cif`, apply manipulations once, write canonical base tables, and cache prepared structures
2. `plugins`
   read prepared structures and emit prefixed columns into the normalized tables
3. `merge`
   merge plugin outputs into final tables
4. `dataset analyses`
   run aggregate analyses on the final merged dataset

Dataset composition is separate:

- `merge-datasets`
  stack multiple completed datasets into one final dataset
- `run-chunked`
  split one input dataset into chunks, run them in parallel, then merge the results

High-level flow:

```text
input structures
    |
    v
prepare
    |
    +--> canonical base tables
    +--> cached prepared structures
    |
    v
plugins
    |
    +--> plugin-specific parquet outputs
    |
    v
merge
    |
    +--> final structures/chains/roles/interfaces tables
    +--> plugin_status.parquet
    +--> bad_files.parquet
    +--> run_metadata.json
    |
    v
dataset analyses
    |
    +--> out_dir/dataset_analysis/*
```

![High-Level Runtime](analysis/highlevel_runtime.svg)

### Package layout

The package is split into three internal layers:

- [minimum_atw/core](/home/eva/minimum_atomworks/minimum_atw/core)
  core application layer: config, normalized table rules, registries, pipeline orchestration
- [minimum_atw/runtime](/home/eva/minimum_atomworks/minimum_atw/runtime)
  execution mechanics: workspace handling, chunk execution, buffered stage output
- [minimum_atw/plugins](/home/eva/minimum_atomworks/minimum_atw/plugins)
  built-in manipulations, record plugins, and dataset analyses

Public entrypoints stay at the package root:

- [minimum_atw/cli.py](/home/eva/minimum_atomworks/minimum_atw/cli.py)
- [minimum_atw/__init__.py](/home/eva/minimum_atomworks/minimum_atw/__init__.py)

Important modules:

- [core/config.py](/home/eva/minimum_atomworks/minimum_atw/core/config.py)
  runtime configuration model
- [core/tables.py](/home/eva/minimum_atomworks/minimum_atw/core/tables.py)
  normalized table identity keys and merge rules
- [core/pipeline.py](/home/eva/minimum_atomworks/minimum_atw/core/pipeline.py)
  prepare, plugin execution, final merge, dataset merge
- [runtime/workspace.py](/home/eva/minimum_atomworks/minimum_atw/runtime/workspace.py)
  structure loading, prepared workspace layout, row emission helpers
- [runtime/stage_buffer.py](/home/eva/minimum_atomworks/minimum_atw/runtime/stage_buffer.py)
  bounded staging buffers for large runs
- [plugins/base.py](/home/eva/minimum_atomworks/minimum_atw/plugins/base.py)
  shared `Context` and plugin base classes

![High-Level Architecture](analysis/highlevel_architecture.svg)

## Normalized tables

Identity keys:

- `structures`: `path`, `assembly_id`
- `chains`: `path`, `assembly_id`, `chain_id`
- `roles`: `path`, `assembly_id`, `role`
- `interfaces`: `path`, `assembly_id`, `pair`, `role_left`, `role_right`

Plugin outputs are merged by these keys. Non-identity output columns are prefixed
as:

```text
<prefix>__<field>
```

Examples:

- `id__n_atoms_total`
- `iface__n_contact_atom_pairs`
- `abseq__cdr3_sequence`

This keeps the row model stable while allowing plugins to widen the schema.

## Why this shape

The package stays role-driven:

- define semantic roles in YAML
- define interface pairs in terms of those roles
- choose the plugins you want

`prepare` is the main cache boundary:

- raw structures are parsed once
- manipulations are applied once
- prepared structures are reused by all record plugins

This keeps the system simple without duplicating expensive structure loading.

## Installation

Clone the repository and install into a Python 3.11 environment:

```bash
git clone <your-repo-url> minimum_atomworks
cd minimum_atomworks
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

Optional antibody-numbering support:

```bash
python -m pip install -e '.[antibody]'
```

Verify the install:

```bash
minimum-atomworks list-extensions
```

or:

```bash
python -m minimum_atw.cli list-extensions
```

Notes:

- `biotite`, `numpy`, `pandas`, `pyarrow`, `pydantic`, and `pyyaml` are core dependencies
- `abnumber` is optional and only needed for antibody-numbering plugins
- Rosetta is not installed by this package
- example YAMLs often contain machine-specific paths and should be copied and edited before use

## CLI commands

Available commands:

- `run`
- `prepare`
- `run-plugin`
- `merge`
- `analyze-dataset`
- `merge-datasets`
- `plan-chunks`
- `merge-planned-chunks`
- `run-chunked`
- `list-extensions`

### One-shot run

```bash
python -m minimum_atw.cli run --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

### Staged run

```bash
python -m minimum_atw.cli prepare --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml --plugin identity
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml --plugin interface_contacts
python -m minimum_atw.cli merge --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
python -m minimum_atw.cli analyze-dataset --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

### Chunked run

```bash
python -m minimum_atw.cli run-chunked \
  --config minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 5 \
  --workers 2
```

### Planned chunks for scheduler arrays

```bash
python -m minimum_atw.cli plan-chunks \
  --config minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --plan-dir /path/to/chunk_plan
```

Then run the generated per-chunk configs in your scheduler and merge them later:

```bash
python -m minimum_atw.cli merge-planned-chunks \
  --plan-dir /path/to/chunk_plan
```

### Manual dataset merge

```bash
python -m minimum_atw.cli merge-datasets \
  --out-dir /path/to/merged_out \
  --source-out-dir /path/to/chunk_out_01 \
  --source-out-dir /path/to/chunk_out_02
```

`merge-datasets` validates source compatibility using output metadata before stacking rows.

In practical terms, datasets are expected to represent the same output schema and
the same structural-analysis setup. For example, they should not be merged if they
were produced with incompatible:

- plugin inventories
- manipulation settings
- interface settings
- antibody numbering settings such as `numbering_scheme` or `cdr_definition`
- final table column sets

## Config model

Core config fields include:

- `input_dir`
- `out_dir`
- `assembly_id`
- `roles`
- `interface_pairs`
- `manipulations`
- `plugins`
- `dataset_analyses`
- `dataset_analysis_params`
- `dataset_annotations`
- `keep_intermediate_outputs`

Antibody-specific options include:

- `numbering_roles`
- `numbering_scheme`
- `cdr_definition`

Other plugin-related runtime options include:

- `contact_distance`
- `superimpose_reference_path`
- `superimpose_on_chains`
- `rosetta_executable`
- `rosetta_database`

## Output layout

Final outputs in `out_dir/`:

- `structures.parquet`
- `chains.parquet`
- `roles.parquet`
- `interfaces.parquet`
- `plugin_status.parquet`
- `bad_files.parquet`
- `run_metadata.json`

Merged dataset outputs also include:

- `dataset_metadata.json`

Dataset-analysis outputs:

- `out_dir/dataset_analysis/*.parquet`
- `out_dir/dataset_analysis/summary.json`

Intermediate outputs, kept only when `keep_intermediate_outputs: true`:

- `out_dir/_prepared/`
- `out_dir/_prepared/prepared_manifest.parquet`
- `out_dir/_prepared/structures/`
- `out_dir/_plugins/<plugin_name>/`

Behavior notes:

- one-shot `run` uses temporary intermediate workspaces unless `keep_intermediate_outputs: true`
- `run-plugin` skips writing empty table parquet files for tables that plugin did not emit
- dataset-analysis reruns clear the old `dataset_analysis/` directory before writing new artifacts

## Metadata and reproducibility

Completed outputs are self-describing:

- `run_metadata.json`
  written for normal completed runs
- `dataset_metadata.json`
  written for merged datasets

These metadata files include:

- row counts
- merge-compatibility information
- final table column lists

This is used to make `merge-datasets` safer and more reproducible.

Merge compatibility is checked in two ways:

- runtime configuration compatibility
  source datasets must agree on the recorded merge-compatibility config
- final schema compatibility
  source datasets must expose the same columns in each normalized table

So if two datasets have incompatible CDR-related settings or one dataset writes
different CDR/interface columns from the other, they are expected to fail before
merge rather than silently combining.

Current scope of the check:

- it does reject incompatible runtime settings such as different numbering configuration
- it does reject incompatible final table schemas
- it does not try to infer semantic differences that are not reflected in config or schema

## Plugin model

There are three extension classes:

- manipulations
- record plugins
- dataset analyses

Requirements:

- extension `name` must be unique
- record plugin `prefix` must be unique and non-empty
- emitted rows must include the identity columns for their target table

Dataset analyses read final outputs and write aggregate artifacts into:

```text
out_dir/dataset_analysis/
```

For antibody numbering plugins:

- roles named `vh`, `vl`, and `vhh` are recognized automatically
- `numbering_roles:` can override role selection
- each numbering role should map to a single protein chain

To inspect registered extensions:

```bash
python -m minimum_atw.cli list-extensions
```

## Examples

Start here:

- [examples/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/README.md)

Detailed example sets:

- [simple_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/README.md)
- [chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md)
- [large_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md)

Main example configs:

- [example_antibody_antigen_pdb.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml)
- [example_antibody_antigen_light.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml)
- [example_vhh_antigen.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml)
- [example_protein_protein_complex.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml)
- [example_antibody_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml)

## Tests

The tests now live under:

- [minimum_atw/tests](/home/eva/minimum_atomworks/minimum_atw/tests)

Main command:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest discover -s minimum_atw/tests -v
```

Detailed test instructions:

- [minimum_atw/tests/README.md](/home/eva/minimum_atomworks/minimum_atw/tests/README.md)
