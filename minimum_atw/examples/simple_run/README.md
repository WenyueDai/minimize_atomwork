# Simple Run Examples

These configs are for local runs, debugging, and plugin development.

Quick start:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
```

## Files

- [example_antibody_antigen_light.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml): smallest antibody-antigen development profile
- [example_antibody_antigen_pdb.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml): fuller antibody-antigen profile
- [example_vhh_antigen.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml): VHH-antigen profile
- [example_protein_protein_complex.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml): generic protein-protein profile

## What is enabled by default

All simple examples show:

- explicit `quality_controls`
- explicit `structure_manipulations`
- explicit `dataset_manipulations`
- the appropriate PDB calculation plugins
- `dataset_annotations`
- `interface_summary`

Antibody-oriented examples also enable:

- `abepitope_score`
- `antibody_cdr_lengths`
- `antibody_cdr_sequences`
- antibody numbering config

Optional and commented by default:

- `rosetta_interface_example`
- `cdr_entropy`

Enabled by default:

- `cluster`

Execution note:

- native `atom_array` plugins are batched together
- external or file-bound plugins such as `abepitope_score` and optional Rosetta run in isolated workers
- those groups can run concurrently during one `run`, so external tools do not have to wait for the full native batch to finish first

Cluster behavior in the examples:

```yaml
dataset_analyses:
  - "cluster"
```

With no extra cluster params, `cluster` emits both `left` and `right` jobs automatically.
Those assignments are written onto interface rows in `pdb.parquet`, not as long-form rows in `dataset.parquet`.

For `["antibody", "antigen"]` that means:

- `right`: antigen epitope clustering
- `left`: antibody paratope clustering

## Useful staged commands

```bash
CONFIG=/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli prepare --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_contacts
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli analyze-dataset --config "$CONFIG"
```

## Notes

- Final outputs are the configured PDB parquet, the configured dataset parquet, and the metadata JSON files.
- `plugin_status.parquet` and `bad_files.parquet` are debug or failure artifacts, not the main outputs.
- AbEpiTope requires both the Python package and `hmmsearch` on `PATH`.
