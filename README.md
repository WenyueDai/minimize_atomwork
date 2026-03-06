# minimum_atomworks

`minimum_atomworks` is a small structural-analysis package built around four normalized tables:

- `structures`
- `chains`
- `roles`
- `interfaces`

The package has three runtime concepts only:

- `prepare`: load raw structures, apply manipulations once, write canonical base tables, and cache prepared structures
- `plugins`: read prepared structures and emit prefixed columns into the normalized tables
- `dataset analyses`: run after merge on the final tables (controlled by the `dataset_analyses` list in config)

It also supports one dataset-composition step for chunked runs:

- `merge-datasets`: stack multiple completed `out_dir` results into one final dataset
- `run-chunked`: split one large dataset into chunks, run them in parallel, and merge the final outputs

It is intended to work with:

- antibody-antigen complexes
- VHH or nanobody binders
- generic protein-protein complexes

## Architecture

High-level runtime shape:

```text
YAML config
    |
    v
Config + role definitions
    |
    v
CLI commands -----------------------------------------------+
    |                                                       |
    | run / run-chunked / prepare / run-plugin / merge      |
    | analyze-dataset / merge-datasets                      |
    v                                                       |
Pipeline ------------------------------------------------+   |
    |                                                    |   |
    | prepare                                            |   |
    v                                                    |   |
raw .pdb/.cif --> Context --> manipulations ----------+  |   |
                                  |                   |  |   |
                                  v                   |  |   |
                      _prepared/ tables + cached aa   |  |   |
                                                      |  |   |
    | run-plugin                                       |  |   |
    v                                                  |  |   |
prepared aa --> record plugin registry --------------> |  |   |
                                  |                    |  |   |
                                  v                    |  |   |
                         _plugins/<plugin>/ tables     |  |   |
                                                      v  v   |
                                                merge outputs |
                                                      |       |
                                                      v       |
                                         final normalized tables
                                     structures / chains / roles / interfaces
                                                      |
                           +--------------------------+------------------+
                           |                                             |
                           v                                             v
                 dataset analyses                               merge-datasets
                           |                                   stacks multiple final
                           v                                   out_dir results
                 dataset_analysis/ artifacts                            |
                                                                        v
                                                             merged final out_dir
```

Core package pieces:

- [cli.py](/home/eva/minimum_atomworks/minimum_atw/cli.py)
  Entry points for all commands.
- [config.py](/home/eva/minimum_atomworks/minimum_atw/config.py)
  Runtime settings, roles, interface pairs, plugin lists.
- [pipeline.py](/home/eva/minimum_atomworks/minimum_atw/pipeline.py)
  Prepare, plugin execution, plugin merge, and dataset merge.
- [plugins/base.py](/home/eva/minimum_atomworks/minimum_atw/plugins/base.py)
  Shared `Context` and base plugin classes.
- [plugins/](/home/eva/minimum_atomworks/minimum_atw/plugins)
  Built-in manipulations, record plugins, and dataset analyses.
- [registry.py](/home/eva/minimum_atomworks/minimum_atw/registry.py)
  Registry loading plus uniqueness checks for names and prefixes.

Merge modes:

```text
Plugin-level merge
------------------
one dataset
    |
    +--> plugin A output  ----+
    +--> plugin B output  ----+--> merge
    +--> plugin C output  ----+
                               |
                               v
                    one final out_dir with wider tables
                    same rows, more columns


Dataset-level merge
-------------------
chunk 1 final out_dir ----+
chunk 2 final out_dir ----+--> merge-datasets
chunk 3 final out_dir ----+
                            |
                            v
                 one merged out_dir with taller tables
                 more rows, same normalized schema
```

## Why this shape

The package is meant to stay easy to read and copy:

- one shared `Context`
- one registry for record plugins
- one registry for dataset analyses
- one authoritative `plugin_status.parquet`
- one authoritative `bad_files.parquet`

`prepare` is now a real cache boundary. A staged run does not reparse raw structures or reapply manipulations for every plugin.

The package stays role-driven rather than modality-driven:

- define semantic roles in YAML
- define interface pairs in terms of those roles
- choose plugins that make sense for your system

Generic plugins such as `identity`, `chain_stats`, `role_sequences`, `role_stats`, and `interface_contacts` work for any protein complex. Antibody-specific plugins are optional add-ons for roles that represent single-chain variable domains.

## Install On Another Computer

Clone the repository first, then install into a clean Python 3.11 environment:

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

Verify the install:

```bash
minimum-atomworks list-extensions
```

You can also use the module form:

```bash
python -m minimum_atw.cli list-extensions
```

Notes:

- When `superimpose_homology` is enabled but `superimpose_reference_path` is unset, the first input structure encountered becomes the implicit reference (that file is left unchanged).

- `biotite`, `numpy`, `pandas`, `pyarrow`, `pydantic`, and `pyyaml` are installed automatically.
- `abnumber` is optional and only needed for antibody-numbering plugins.
- Rosetta is not installed by this package. The Rosetta example plugin requires a separate Rosetta installation.
- Example YAML files are shipped with the package, but most of them contain machine-specific paths for `input_dir`, `out_dir`, `superimpose_reference_path`, and optional Rosetta locations. Copy an example and update those paths for the target machine before running it.

## Run

One-shot execution:

```bash
python -m minimum_atw.cli run --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

Staged execution:

```bash
python -m minimum_atw.cli prepare --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml --plugin identity
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml --plugin interface_contacts
python -m minimum_atw.cli merge --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
python -m minimum_atw.cli analyze-dataset --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

`run-plugin` expects prepared outputs to exist already.

Chunked dataset workflow:

```bash
python -m minimum_atw.cli run-chunked \
  --config minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml \
  --chunk-size 5 \
  --workers 2
```

`run-chunked` splits one `input_dir` into temporary chunks, runs those chunks in parallel, merges the final chunk outputs into `out_dir`, optionally runs dataset analysis once on the merged result, and then removes the temporary chunk workspace.

For advanced control, you can still run manual chunks yourself and combine them later with `merge-datasets`.

Example configs (note the absence of the obsolete `dataset_analysis` boolean):

- [antibody-antigen](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml)
- [VHH-antigen](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml)
- [protein-protein complex](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml)
- [large-run chunked example](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml)
- [simple-run README](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/README.md)
- [chunk-run README](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md)
- [large-run README](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md)

Portable config checklist for a new machine:

- set `input_dir` to the directory that contains your `.pdb` or `.cif` files
- set `out_dir` to a writable output directory on that machine
- set `superimpose_reference_path` only if you enable `superimpose_homology` (if omitted, the first structure encountered will serve as the reference)
- set `superimpose_on_chains` to the chain IDs used as the alignment anchor
- set `rosetta_executable` and `rosetta_database` only if you plan to enable the Rosetta example plugin
- use `dataset_analyses:` (a list) to request dataset-level summaries; the boolean `dataset_analysis` has been removed

## Output layout

Final outputs in `out_dir/`:

- `structures.parquet`
- `chains.parquet`
- `roles.parquet`
- `interfaces.parquet`
- `plugin_status.parquet`
- `bad_files.parquet`

Intermediate outputs, kept only when `keep_intermediate_outputs: true`:

- `out_dir/_prepared/`
- `out_dir/_prepared/prepared_manifest.parquet`
- `out_dir/_prepared/structures/`
- `out_dir/_plugins/<plugin_name>/`
- `out_dir/dataset_analysis/`

In one-shot `run`, if `keep_intermediate_outputs: false`, the package now uses a temporary workspace for `_prepared/` and `_plugins/` and only writes the final merged outputs into `out_dir/`.

For chunked workflows, `run-chunked` also uses a temporary chunk workspace. Only the merged final tables plus optional dataset-analysis artifacts are kept in the real `out_dir/`.

## Extension model

Record plugins emit rows keyed by the normalized table identity columns. The pipeline prefixes non-identity columns as `<prefix>__<field>`.

Requirements:

- plugin `name` must be unique
- plugin `prefix` must be unique and non-empty
- emitted rows must contain the identity columns for their target table

Dataset analyses read final merged tables and write aggregate artifacts under `out_dir/dataset_analysis/`.

For antibody numbering plugins:

- the package auto-detects roles named `vh`, `vl`, or `vhh`
- you can override that with `numbering_roles:` in the config
- each numbering role should correspond to a single protein chain

To inspect registered extensions:

```bash
python -m minimum_atw.cli list-extensions
```
