# Simple Run Examples

These configs are for small local runs and day-to-day plugin development.

The examples now follow one rule:

- enable built-in local plugins that fit the example
- keep Rosetta scaffolded but commented out by default
- enable AbEpiTope by default in antibody-oriented examples

## Quick start

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
```

## Example files

- [example_antibody_antigen_light.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml): local antibody-antigen development profile
- [example_antibody_antigen_pdb.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml): full antibody-antigen example with built-in plugins active
- [example_vhh_antigen.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml): VHH-focused variant
- [example_protein_protein_complex.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml): generic non-antibody variant

## What is active by default

Antibody and VHH examples enable:

- both built-in quality controls
- the built-in PDB manipulation
- the built-in dataset manipulation
- the built-in PDB calculation plugins
- `abepitope_score`
- dataset annotations
- interface summary
- `dataset_analysis_mode: post_merge`

That includes both interface plugins:

- `interface_contacts` for atom/residue contact outputs
- `interface_metrics` for residue-property and residue-contact-pair outputs

`cdr_entropy` is scaffolded but commented out by default. Enable it only when you want CDR rows in the dataset parquet.

The generic protein-protein example leaves antibody-only features commented because they do not apply to that role model.

These runs write one final PDB parquet plus one dataset parquet, unless you override the filenames with `pdb_output_name` and `dataset_output_name`.

## Enabling Rosetta later

Every relevant YAML already includes the full Rosetta scaffold. To turn it on:

1. uncomment `rosetta_interface_example` in `plugins`
2. uncomment and fill `rosetta_executable` and `rosetta_database`
3. optionally uncomment `score_jd2` preprocessing and `rosetta_interface_targets`

The Rosetta block already includes:

- preprocess-with-`score_jd2`
- packed vs no-pack settings
- packstat options
- native `-fixedchains` targets

## AbEpiTope note

The antibody-oriented example YAMLs now enable `abepitope_score` and `abepitope_atom_radius` by default.

Run those examples only when:

- `abepitope` is installed in the active Python environment
- `hmmsearch` is on `PATH`

If those dependencies are not available, comment `abepitope_score` back out in the YAML.

## Useful staged commands

```bash
CONFIG=/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli prepare --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_contacts
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli analyze-dataset --config "$CONFIG"
```
