# minimum_atomworks

`minimum_atomworks` is a structural data-processing package for protein complexes.

It produces one unified PDB-side table plus optional dataset-level analysis output:

- `pdb.parquet`
- `dataset.parquet`

It is designed for:

- antibody-antigen complexes
- VHH or nanobody binders
- generic protein-protein complexes

The package is built around a simple idea:

1. prepare structures once
2. run PDB calculation plugins that add prefixed columns
3. merge into the final PDB parquet
4. optionally run dataset-level analyses

## Runtime Overview

Main pipeline:

- `prepare`
  load structures, run PDB and dataset prepare units, cache prepared structures when requested
- `pdb calculations`
  emit prefixed columns into unified PDB rows
- `merge`
  build final `pdb` output plus runtime metadata
- `dataset analyses`
  read merged `pdb` output and write `dataset` output

Large-dataset paths:

- `run-chunked`
  one larger job, internal chunk parallelism via `--workers`
- `plan-chunks` + `merge-planned-chunks`
  generate scheduler-ready chunk configs, run them externally, then merge
- `merge-datasets`
  stack already completed datasets, as long as they are compatible

![High-Level Runtime](minimum_atw/analysis/runtime.svg)

## Architecture Overview

The package has three internal layers:

- [minimum_atw/core](/home/eva/minimum_atomworks/minimum_atw/core)
  config, row-identity rules, registries, orchestration
- [minimum_atw/runtime](/home/eva/minimum_atomworks/minimum_atw/runtime)
  execution mechanics, chunk planning, workspace layout, spill buffers
- [minimum_atw/plugins](/home/eva/minimum_atomworks/minimum_atw/plugins)
  PDB and dataset extension implementations

Public entrypoints:

- [minimum_atw/__init__.py](/home/eva/minimum_atomworks/minimum_atw/__init__.py)
- [minimum_atw/cli.py](/home/eva/minimum_atomworks/minimum_atw/cli.py)

![High-Level Architecture](minimum_atw/analysis/architecture.svg)

Current plugin taxonomy:

- `pdb/quality_control`
- `pdb/manipulation`
- `pdb/calculation`
- `dataset/quality_control`
- `dataset/manipulation`
- `dataset/calculation`

## PDB Table

The final PDB parquet stores all PDB-side outputs together. Row grain is encoded in `grain`:

- `structure`
- `chain`
- `role`
- `interface`

Identity columns:

- `path`
- `assembly_id`
- `grain`
- `chain_id`
- `role`
- `pair`
- `role_left`
- `role_right`

Plugin outputs are merged by identity keys. Non-identity fields are prefixed:

```text
<prefix>__<field>
```

Examples:

- `id__n_atoms_total`
- `iface__n_contact_atom_pairs`
- `abseq__cdr3_sequence`
- `abepitope__score`

Internal helper modules such as [interface_metrics.py](/home/eva/minimum_atomworks/minimum_atw/plugins/pdb/calculation/interface_analysis/interface_metrics.py) support plugins but are not themselves YAML-selectable extensions.

Most dataset analyses write a second parquet, usually `dataset.parquet`, with an `analysis` column instead of `grain`. Dataset-level clustering is the main exception: it is computed at dataset scope but writes its assignments back onto `pdb.parquet` interface rows.

## Installation

```bash
git clone <your-repo-url> minimum_atomworks
cd minimum_atomworks
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

Optional antibody numbering support:

```bash
python -m pip install -e '.[antibody]'
```

Optional AbEpiTope support:

```bash
python -m pip install git+https://github.com/mnielLab/AbEpiTope-1.0
conda install -c bioconda hmmer
```

List extensions:

```bash
python -m minimum_atw.cli list-extensions
```

Notes:

- `abnumber` is optional
- `abepitope` and `hmmsearch` are only needed when `abepitope_score` is enabled
- Rosetta is not installed by this package
- example YAMLs usually need path edits before reuse on another machine

## Common Commands

One-shot run:

```bash
python -m minimum_atw.cli run --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

Staged run:

```bash
python -m minimum_atw.cli prepare --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml --plugin identity
python -m minimum_atw.cli merge --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
python -m minimum_atw.cli analyze-dataset --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

Automatic chunked run:

```bash
python -m minimum_atw.cli run-chunked \
  --config minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --workers 4
```

Scheduler-ready chunk planning:

```bash
python -m minimum_atw.cli plan-chunks \
  --config minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --plan-dir /path/to/chunk_plan
```

Merge planned chunks:

```bash
python -m minimum_atw.cli merge-planned-chunks --plan-dir /path/to/chunk_plan
```

Merge completed datasets:

```bash
python -m minimum_atw.cli merge-datasets \
  --out-dir /path/to/merged_out \
  --source-out-dir /path/to/out_a \
  --source-out-dir /path/to/out_b
```

## Output Layout

Final outputs in `out_dir/`:

- configured PDB parquet, `pdb.parquet` by default
- `run_metadata.json`

Dataset-level outputs:

- configured dataset parquet, `dataset.parquet` by default
- `dataset_metadata.json`

Optional naming keys in YAML:

- `pdb_output_name: 20250212_pdb.parquet`
- `dataset_output_name: 20250212_dataset.parquet`

Failure/debug output:

- `plugin_status.parquet` is only written for intermediate/checkpointed runs or when any plugin status is non-`ok`
- `bad_files.parquet` is only written when failures occur
- `_prepared/` and flat `_plugins/` artifacts are only kept when `keep_intermediate_outputs: true`

`run_metadata.json` and `dataset_metadata.json` also record `output_files` so downstream tools can resolve custom parquet names reliably.

## Merge Compatibility

Datasets should only be merged if they represent the same analysis setup.

`merge-datasets` checks:

- recorded runtime compatibility
- final table-column compatibility

So merges are expected to fail if datasets differ in important settings such as:

- active plugins
- prepare-stage semantics
- interface settings
- antibody numbering settings like `numbering_scheme` or `cdr_definition`
- final parquet schema

Output filenames do not affect merge compatibility. Different runs can still merge as long as the actual schema and runtime settings match.

## Examples

Start here:

- [examples/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/README.md)

Detailed guides:

- [simple_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/README.md)
- [chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md)
- [large_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md)

YAML config field meanings:

- [examples/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/README.md)

## Tests

Tests live under:

- [minimum_atw/tests](/home/eva/minimum_atomworks/minimum_atw/tests)

Run them with:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest discover -s minimum_atw/tests -v
```

Detailed test instructions:

- [minimum_atw/tests/README.md](/home/eva/minimum_atomworks/minimum_atw/tests/README.md)
