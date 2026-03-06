# Simple Run Examples

This folder contains complete example YAML files for running one dataset in one output directory.

Files:

- `example_antibody_antigen_pdb.yaml`
- `example_antibody_antigen_light.yaml`
- `example_vhh_antigen.yaml`
- `example_protein_protein_complex.yaml`

Built-in extension surface shown in the examples:

- manipulations: `center_on_origin`, `superimpose_homology`
- record plugins: `identity`, `chain_stats`, `role_sequences`, `role_stats`, `interface_contacts`, `antibody_cdr_lengths`, `antibody_cdr_sequences`, `rosetta_interface_example`
- dataset analyses: `dataset_annotations`, `interface_summary`, `cdr_entropy`

The YAML files list as much of that surface as possible directly in comments. When only one option can be active at a time, the alternatives are kept commented out next to the active setting.

For antibody/VHH examples, `interface_contacts` now writes both whole-interface residue columns and CDR-specific interface columns when `numbering_roles` is configured. The interface table can therefore include fields such as:

- `iface__left_interface_residues`
- `iface__right_interface_residues`
- `iface__n_left_vh_cdr1_interface_residues`
- `iface__left_vh_cdr1_interface_residues`
- `iface__n_left_vl_cdr3_interface_residues`
- `iface__left_vl_cdr3_interface_residues`

Those residue lists use `chain:resi:resn` with 1-letter residue codes.

Run one of them with:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

Staged workflow:

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

Other ready-to-run configs on this machine:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml
```

Slurm one-shot example:

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

Slurm staged example:

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

Notes:

- These YAML files are concrete examples, not guaranteed turnkey runs on every machine.
- The Rosetta paths are filled in, but the Rosetta plugin is commented out by default because it depends on an external Rosetta install.
- Antibody numbering examples keep one active `numbering_scheme` and `cdr_definition`, with the other valid combinations commented out beside them.
- In the antibody and VHH configs, `interface_contacts` uses those numbering settings to add per-CDR contact residue columns to `interfaces.parquet`.
- `cdr_entropy` examples show region and role filters in comments because only one selection can be active for a given run configuration.
- On this machine, the four YAML files above already point at real input data and absolute output paths.
