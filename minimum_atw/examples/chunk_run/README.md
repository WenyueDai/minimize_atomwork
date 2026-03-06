# Chunk Run Examples

This folder is for manual chunk configs.

Use this workflow if:

- you want one scheduler job per chunk
- you want to control each chunk config explicitly
- you want a simple manual path for debugging staged runs

If you want one large orchestrated command instead, use [large_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md).

## Files

- `chunk_antibody_antigen_01.yaml`
- `chunk_antibody_antigen_02.yaml`
- `chunk_config_manifest_example.txt`

## Key rule

Input filenames do not need any shared numeric pattern.

`chunk_run` only requires:

- each chunk config points at a real `input_dir`
- each chunk input directory contains valid `.pdb` or `.cif` files
- each chunk writes to its own `out_dir`

So filenames like these are fine:

- `binder_A_model_final.pdb`
- `7xyz_relaxed_decoy_alpha.pdb`
- `candidate_nanobody_redo_2026_03_01.cif`

## What this workflow looks like

1. run each chunk config separately
2. each chunk produces a complete final `out_dir`
3. merge the finished chunk outputs with `merge-datasets`
4. optionally run dataset analysis on the merged dataset

This is the right workflow when parallelism is owned by the scheduler, not by `minimum_atw`.

## Run the example chunks

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml
```

## Merge the finished chunk outputs

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge-datasets \
  --out-dir /home/eva/minimum_atomworks/out_antibody_antigen_merged \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_01 \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_02
```

## Optional dataset analysis on the merged result

Point `out_dir` in a config file at:

```text
/home/eva/minimum_atomworks/out_antibody_antigen_merged
```

Then run:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli analyze-dataset \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

## Staged chunk workflow

Use this only if you want to inspect each stage for a chunk.

```bash
CONFIG=/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli prepare --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin identity
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin chain_stats
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_sequences
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_stats
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_contacts
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge --config "$CONFIG"
```

## Example data on this machine

These chunk YAMLs point at real data here:

- `/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/data/chunk_01`
- `/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/data/chunk_02`
- `/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/data/reference/7e9b_reference_rank_001.pdb`

## Slurm patterns

### One job per explicit chunk config

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk-01
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml
EOF
```

### Slurm array with numeric chunk config names

```bash
sbatch --array=1-2 <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%A_%a.out
set -euo pipefail

cd /home/eva/minimum_atomworks

CONFIG=/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_0${SLURM_ARRAY_TASK_ID}.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run --config "$CONFIG"
EOF
```

### Slurm array with arbitrary chunk config names

Use a manifest file and let each array task read one line from it.

Example manifest:

- [chunk_config_manifest_example.txt](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_config_manifest_example.txt)

To use the shipped example manifest:

```bash
MANIFEST=/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_config_manifest_example.txt
```

Generic pattern:

```bash
sbatch --array=1-3 <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%A_%a.out
set -euo pipefail

cd /home/eva/minimum_atomworks

MANIFEST=/home/eva/minimum_atomworks/path/to/chunk_config_manifest.txt
CONFIG=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$MANIFEST")

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run --config "$CONFIG"
EOF
```

This is the safest pattern when chunk config names are arbitrary.

### Merge job

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk-merge
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge-datasets \
  --out-dir /home/eva/minimum_atomworks/out_antibody_antigen_merged \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_01 \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_02
EOF
```

## Notes

- These manual chunk examples keep `numbering_roles` and `interface_contacts` enabled, so merged `interfaces.parquet` can contain antibody CDR interface columns.
- Chunk outputs must still be compatible before merge. Different numbering setup or different final table columns are expected to fail the merge.
- If you want automatically generated scheduler-ready chunk configs from one large config, use `plan-chunks` in [large_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md).
