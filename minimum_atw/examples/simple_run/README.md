# Simple Run Examples

These configs are for small local runs and day-to-day plugin development.

The examples now follow one rule:

- enable built-in local plugins that fit the example
- keep heavy external plugins such as Rosetta and AbEpiTope present, but commented out by default

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
- the built-in per-structure manipulation
- the built-in dataset-scale manipulation
- the built-in record plugins
- dataset annotations
- interface summary
- CDR entropy
- `dataset_analysis_mode: post_merge`

That includes both interface plugins:

- `interface_contacts` for atom/residue contact outputs
- `interface_metrics` for residue-property and residue-contact-pair outputs

The generic protein-protein example leaves antibody-only features commented because they do not apply to that role model.

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

## Enabling AbEpiTope later

The antibody-oriented example YAMLs also include a commented `abepitope_score` plugin entry and `abepitope_atom_radius`.

Enable it only when:

- `abepitope` is installed in the active Python environment
- `hmmsearch` is on `PATH`

The plugin is a heavy isolated external score plugin for antibody-antigen style interfaces.

## Useful staged commands

```bash
CONFIG=/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli prepare --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_contacts
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli analyze-dataset --config "$CONFIG"
```
