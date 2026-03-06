# Simple Run Examples

This folder is for one dataset -> one output directory.

Use these examples if:

- you want the easiest way to run `minimum_atomworks`
- you want to inspect one finished dataset
- you are testing plugin behavior or schema changes

## Files

- `example_antibody_antigen_pdb.yaml`
- `example_antibody_antigen_light.yaml`
- `example_vhh_antigen.yaml`
- `example_protein_protein_complex.yaml`

## What these examples show

The YAML files expose the built-in feature surface directly in comments.

They show:

- manipulations
  `center_on_origin`, `superimpose_homology`
- record plugins
  `identity`, `chain_stats`, `role_sequences`, `role_stats`, `interface_contacts`, `antibody_cdr_lengths`, `antibody_cdr_sequences`, `rosetta_interface_example`
- dataset analyses
  `dataset_annotations`, `interface_summary`, `cdr_entropy`

When only one option can be active, the alternatives are left commented out next to the chosen value.

## Which config should you start with?

Use `example_antibody_antigen_pdb.yaml` if:

- you want the most complete antibody example
- you want interface contact output plus antibody CDR output

Use `example_antibody_antigen_light.yaml` if:

- you want a faster run
- you want fewer active plugins

Use `example_vhh_antigen.yaml` if:

- your system is a nanobody or VHH binder

Use `example_protein_protein_complex.yaml` if:

- your system is a generic protein-protein complex
- you do not want antibody-specific output

## Fastest command

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

## Staged workflow

Use this only if you want to inspect each stage separately.

```bash
CONFIG=/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli prepare --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin identity
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin chain_stats
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_sequences
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_stats
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_contacts
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli analyze-dataset --config "$CONFIG"
```

## Important output notes

In antibody and VHH examples, `interface_contacts` can write:

- whole-interface residue columns
  `iface__left_interface_residues`, `iface__right_interface_residues`
- CDR-specific interface columns
  `iface__n_left_vh_cdr1_interface_residues`, `iface__left_vh_cdr1_interface_residues`, `iface__n_left_vl_cdr3_interface_residues`, `iface__left_vl_cdr3_interface_residues`

Residue tokens use:

```text
chain:resi:resn
```

with 1-letter residue codes.

## Other ready-to-run commands

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml
```

## Slurm examples

One-shot:

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-simple
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
EOF
```

Staged:

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-simple-staged
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

CONFIG=/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli prepare --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin identity
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin chain_stats
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_sequences
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_stats
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_contacts
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli analyze-dataset --config "$CONFIG"
EOF
```

## Notes

- These configs are concrete examples, not a promise that every machine has the same data paths.
- The Rosetta example plugin stays commented out by default because it depends on an external Rosetta installation.
- Antibody numbering examples keep one active `numbering_scheme` and `cdr_definition`, with other valid choices shown as comments.
- `cdr_entropy` examples also show role and region selection variants in comments.
