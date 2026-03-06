# Chunk Run Examples

This folder shows the manual chunk workflow.

For the preferred automatic workflow, use `run-chunked` on one config instead of creating chunk YAML files yourself.

Files:

- `chunk_antibody_antigen_01.yaml`
- `chunk_antibody_antigen_02.yaml`

Run the chunks:

```bash
python -m minimum_atw.cli run --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml
python -m minimum_atw.cli run --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml
```

Staged manual chunk workflow:

```bash
python -m minimum_atw.cli prepare --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml --plugin identity
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml --plugin chain_stats
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml --plugin role_sequences
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml --plugin role_stats
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml --plugin interface_contacts
python -m minimum_atw.cli merge --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml

python -m minimum_atw.cli prepare --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml --plugin identity
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml --plugin chain_stats
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml --plugin role_sequences
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml --plugin role_stats
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml --plugin interface_contacts
python -m minimum_atw.cli merge --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml
```

Merge the finished chunk outputs:

```bash
python -m minimum_atw.cli merge-datasets \
  --out-dir /home/eva/minimum_atomworks/out_antibody_antigen_merged \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_01 \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_02
```

Then, if you want dataset-level summaries on the merged result, run:

```bash
python -m minimum_atw.cli analyze-dataset --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

Before running that analysis command, point `out_dir` in the YAML at:

```text
/home/eva/minimum_atomworks/out_antibody_antigen_merged
```

How this is intended to work:

- each chunk YAML writes a complete final `out_dir`
- chunk configs omit the deprecated `dataset_analysis` key so that dataset summaries are only run on the merged result
- `merge-datasets` merges those final chunk outputs row by row into one new final `out_dir`
- dataset analysis is a separate step on the merged dataset

Adjust the chunk input directories and reference path to match your machine before running.

Automatic alternative:

```bash
python -m minimum_atw.cli run-chunked \
  --config minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml \
  --chunk-size 5 \
  --workers 2
```

That command creates temporary chunks internally, runs them, merges the chunk outputs into the final `out_dir`, and removes the temporary chunk workspace afterward.

Slurm manual chunk example:

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk-01
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /path/to/minimum_atomworks
source .venv/bin/activate

python -m minimum_atw.cli run \
  --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml
EOF

sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk-02
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /path/to/minimum_atomworks
source .venv/bin/activate

python -m minimum_atw.cli run \
  --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml
EOF
```

Slurm merge job:

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk-merge
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /path/to/minimum_atomworks
source .venv/bin/activate

python -m minimum_atw.cli merge-datasets \
  --out-dir /path/to/out_antibody_antigen_merged \
  --source-out-dir /path/to/out_chunk_antibody_antigen_01 \
  --source-out-dir /path/to/out_chunk_antibody_antigen_02
EOF
```

Slurm staged chunk example:

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk-01-staged
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /path/to/minimum_atomworks
source .venv/bin/activate

CONFIG=minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml

python -m minimum_atw.cli prepare --config "$CONFIG"
python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin identity
python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin chain_stats
python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_sequences
python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_stats
python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_contacts
python -m minimum_atw.cli merge --config "$CONFIG"
EOF
```
