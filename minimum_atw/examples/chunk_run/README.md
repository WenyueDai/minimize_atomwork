# Chunk Run Examples

This folder is for manual chunk configs: one config per chunk, one run per config, then an explicit merge.

## Files

- [chunk_antibody_antigen_01.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml)
- [chunk_antibody_antigen_02.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml)
- [chunk_config_manifest_example.txt](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_config_manifest_example.txt)

## Run the chunks

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml
```

## Merge the finished chunks

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge-datasets \
  --out-dir /home/eva/minimum_atomworks/out_antibody_antigen_merged \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_01 \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_02
```

## What these YAMLs show

- explicit manual chunk outputs
- `dataset_analysis_mode: per_chunk`
- optional checkpoint settings
- optional Rosetta scaffold
- optional `cdr_entropy`
- enabled interface clustering

Execution note:

- native `atom_array` plugins stay batched
- external or file-bound plugins stay isolated
- those groups can run concurrently within each chunk config

Clustering note:

- These chunk YAMLs now do enable `cluster`, so they write per-chunk cluster labels onto interface rows in each chunk's `pdb.parquet`.
- If you want biologically meaningful whole-dataset clusters, merge first and then run `analyze-dataset` on the merged output with a config that enables `cluster`.

Cluster behavior in the chunk examples:

```yaml
dataset_analyses:
  - "cluster"
```

With no extra cluster params, each chunk run emits both `left` and `right` cluster jobs.

## Scheduler pattern

```bash
MANIFEST=/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_config_manifest_example.txt
```

Generic array-job pattern:

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
