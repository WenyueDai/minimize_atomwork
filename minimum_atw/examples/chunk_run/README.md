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

## Step By Step: What This Manual Chunk Workflow Does

Using [chunk_antibody_antigen_01.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml) and [chunk_antibody_antigen_02.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml):

1. You choose the chunk boundaries yourself and write one YAML per chunk.
2. Each `run` command executes a normal single-dataset pipeline for that one chunk.
3. Inside each chunk run, `prepare` loads structures and runs:
   - `chain_continuity`
   - `structure_clashes`
   - `center_on_origin`
   - `superimpose_to_reference`
4. The aligned prepared structures are saved under that chunk's `_prepared/` directory.
5. The configured plugins run on the already-aligned prepared structures.
6. Because these chunk YAMLs use `dataset_analysis_mode: per_chunk`, dataset analyses run inside each chunk output.
7. That means each chunk gets its own `dataset.parquet`, and `cluster` writes chunk-local cluster labels onto each chunk's `pdb.parquet`.
8. After all chunks finish, `merge-datasets` stacks the chunk outputs into one merged dataset.
9. That merge keeps the final `pdb.parquet`, `dataset__id`, and `dataset__name`, but it does not recompute biologically meaningful whole-dataset clusters by itself.
10. If you want whole-dataset clustering, run `analyze-dataset` on the merged output with a config that enables `cluster`.

### What Persists

- Each chunk keeps its own `_prepared/` directory by default.
- The merged output does not automatically get a merged `_prepared/` cache.
- If you enable `cleanup_prepared_after_dataset_analysis: true` in a chunk YAML, that chunk's `_prepared/` directory is removed only after its dataset analysis succeeds.

## What these YAMLs show

- explicit manual chunk outputs
- `dataset_analysis_mode: per_chunk`
- optional checkpoint settings
- optional Rosetta scaffold
- optional `cdr_entropy`
- enabled interface clustering

See [../README.md](/home/eva/minimum_atomworks/minimum_atw/examples/README.md) for the field-by-field glossary and when to turn each option on or off.

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
