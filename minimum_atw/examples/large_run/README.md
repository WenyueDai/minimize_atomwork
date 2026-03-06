# Large Run Example

This folder is for large datasets.

Use it if:

- you want automatic chunking with `run-chunked`
- you want one larger job with internal parallel workers
- or you want `plan-chunks` to generate scheduler-ready chunk configs for a Slurm array

## File

- `example_antibody_antigen_chunked.yaml`

## Two valid workflows

### 1. One larger job, internal parallelism

Use `run-chunked` when you want `minimum_atw` to manage chunk creation and worker scheduling.

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --workers 4
```

What happens:

- one `input_dir` is discovered
- temporary chunks are created internally
- chunks run in parallel through `--workers`
- chunk outputs are merged automatically
- dataset analysis runs once on the merged result
- the temporary chunk workspace is removed

Use this when:

- one allocation is enough
- you want the simplest large-run command

### 2. Scheduler-managed chunk jobs

Use `plan-chunks` if you want Slurm arrays or one scheduler job per chunk.

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli plan-chunks \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --plan-dir /home/eva/minimum_atomworks/out_antibody_antigen_chunk_plan
```

That creates:

- one deterministic chunk input directory per chunk
- one generated `config.yaml` per chunk
- one `chunk_plan.json` manifest for the whole run

Then run the generated configs as separate jobs and merge them:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge-planned-chunks \
  --plan-dir /home/eva/minimum_atomworks/out_antibody_antigen_chunk_plan
```

Use this when:

- you want Slurm arrays
- you want easier chunk retries
- you want the scheduler, not `minimum_atw`, to own chunk parallelism

## Important naming note

The original input structure filenames do not need to be numbered or share any index pattern.

`plan-chunks` discovers whatever `.pdb` and `.cif` files exist, then creates its own generated chunk directories:

- `chunk_0001/`
- `chunk_0002/`
- ...

The scheduler only targets the generated `config.yaml` files.

## Start smaller first

Dry run:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --workers 2
```

## Slurm examples

### Single larger job with internal workers

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-large
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --workers 4
EOF
```

This is one Slurm job, not one job per chunk.

### Slurm array with planned chunks

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli plan-chunks \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --plan-dir /home/eva/minimum_atomworks/out_antibody_antigen_chunk_plan

sbatch --array=1-10 <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-planned-chunk
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%A_%a.out
set -euo pipefail

cd /home/eva/minimum_atomworks

CONFIG=$(printf "/home/eva/minimum_atomworks/out_antibody_antigen_chunk_plan/chunk_%04d/config.yaml" "$SLURM_ARRAY_TASK_ID")

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run --config "$CONFIG"
EOF
```

After the array finishes:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge-planned-chunks \
  --plan-dir /home/eva/minimum_atomworks/out_antibody_antigen_chunk_plan
```

## Output notes

- The merged `interfaces.parquet` can contain antibody CDR contact fields if `numbering_roles` and `interface_contacts` are enabled.
- Planned or automatic chunk outputs still have to be compatible before merge.
- If you need fully hand-written chunk YAMLs instead of auto-generated chunk configs, use [chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md).
