# Chunk Run Examples

This folder is for manual chunk configs.

Use this workflow if:

- you want **one scheduler job per chunk** with explicit scheduler control
- you want to debug each chunk independently
- your HPC cluster manages parallelism (e.g., Slurm array jobs)
- you want manual orchestration of Rosetta parallelization

If you want one large orchestrated command with internal parallelism, use [large_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md) instead.

## Files

- `chunk_antibody_antigen_01.yaml` (includes Rosetta)
- `chunk_antibody_antigen_02.yaml` (includes Rosetta)
- `chunk_config_manifest_example.txt`

## Resource Strategy

When running chunks as separate scheduler jobs:

| Setup | Parallelism | Resource Efficiency |
|-------|-------------|-------------------|
| 100 structures, 4 chunks × 25 each | 4 Rosetta jobs in parallel | Good (4 CPU) |
| 100 structures, 10 chunks × 10 each | 10 Rosetta jobs in parallel | ~OK (10 CPU needed) |
| 100 structures, 100 chunks × 1 each | 100 Rosetta jobs (rarely useful) | Poor (many small jobs) |

**Recommended:** 5-20 structures per chunk so Rosetta work is balanced.

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

## Rosetta Setup

All chunk configs include `rosetta_interface_example`. Configure Rosetta before running:

```bash
export ROSETTA_INTERFACE_ANALYZER="/path/to/InterfaceAnalyzer.static.linuxgccrelease"
export ROSETTA_DATABASE="/path/to/rosetta/database"
```

Or edit each YAML config directly.

## What this workflow looks like

1. **run each chunk config separately** (each can be a Slurm job)
2. **each chunk produces its own complete final `out_dir`** (with Rosetta metrics)
3. **merge the finished chunk outputs** with `merge-datasets`
4. **(optional) run dataset analysis** on the merged dataset

This workflow is ideal when:

- your HPC scheduler (Slurm) manages chunk parallelism
- you want per-chunk retries without re-running the whole dataset
- multiple Rosetta jobs run simultaneously (one per chunk job)

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

Use this only if you want to inspect each stage for a chunk (including Rosetta):

```bash
CONFIG=/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli prepare --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin identity
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin chain_stats
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_sequences
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_stats
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_contacts
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin rosetta_interface_example  # slowest step
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge --config "$CONFIG"
```

## Example data on this machine

These chunk YAMLs point at real data here:

- `/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/data/chunk_01`
- `/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/data/chunk_02`
- `/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/data/reference/7e9b_reference_rank_001.pdb`

## Slurm Examples

### Sequential chunk jobs (simple, slow)

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk-01
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml
EOF

sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk-02
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml
EOF
```

### Parallel chunk jobs (better, recommended)

Submit all chunks as independent jobs (they run in parallel if queue capacity allows):

```bash
for i in 01 02; do
  sbatch <<EOF
#!/bin/bash
#SBATCH --job-name=chunk-$i
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_$i.yaml
EOF
done
```

### After all chunks complete: merge results

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge-datasets \
  --out-dir /home/eva/minimum_atomworks/out_antibody_antigen_merged \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_01 \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_02
```

**Resource model:** If you submit 10 chunks with `--cpus-per-task=2 --mem=8G`, and the queue allows 10 parallel jobs, all 10 Rosetta processes run simultaneously, completing the entire dataset ~10x faster than sequential processing.

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
