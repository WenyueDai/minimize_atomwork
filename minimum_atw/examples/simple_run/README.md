# Simple Run Examples

This folder contains complete example YAML files for running one dataset in one output directory.

Files:

- `example_antibody_antigen_pdb.yaml`
- `example_vhh_antigen.yaml`
- `example_protein_protein_complex.yaml`

Run one of them with:

```bash
python -m minimum_atw.cli run --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

Staged workflow:

```bash
python -m minimum_atw.cli prepare --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml --plugin identity
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml --plugin chain_stats
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml --plugin role_sequences
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml --plugin role_stats
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml --plugin interface_contacts
python -m minimum_atw.cli merge --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
python -m minimum_atw.cli analyze-dataset --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
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

cd /path/to/minimum_atomworks
source .venv/bin/activate

python -m minimum_atw.cli run \
  --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
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

cd /path/to/minimum_atomworks
source .venv/bin/activate

CONFIG=minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml

python -m minimum_atw.cli prepare --config "$CONFIG"
python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin identity
python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin chain_stats
python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_sequences
python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_stats
python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_contacts
python -m minimum_atw.cli merge --config "$CONFIG"
python -m minimum_atw.cli analyze-dataset --config "$CONFIG"
EOF
```

Notes:

- These YAML files are concrete examples, not guaranteed turnkey runs on every machine.
- The Rosetta paths are filled in, but the Rosetta plugin is not enabled by default.
- Adjust `input_dir`, `out_dir`, and external-tool paths to match your machine if needed.
