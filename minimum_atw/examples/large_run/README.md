# Large Run Example

This folder is for automatic chunked execution with `run-chunked`.

This example uses a different parallelism model than
[chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md):

- submit one larger job
- let `run-chunked --workers N` run chunks in parallel inside that job
- keep chunk orchestration inside `minimum_atw` instead of managing chunk YAMLs yourself

If you want Slurm array jobs to run chunk outputs as separate scheduler tasks, use
the new planned-chunk workflow described below.

Use:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --workers 4
```

Scheduler-managed alternative:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli plan-chunks \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --plan-dir /home/eva/minimum_atomworks/out_antibody_antigen_chunk_plan
```

That command creates:

- one deterministic chunk input directory per chunk
- one generated `config.yaml` per chunk
- one `chunk_plan.json` manifest describing the whole plan

The original input structure filenames do not need to be numbered or share any
common index pattern. `plan-chunks` discovers the files, splits them into chunk
directories, and numbers the chunk directories itself:

- `chunk_0001/`
- `chunk_0002/`
- ...

The scheduler only needs to target the generated chunk config paths. It does not
depend on the original structure filenames.

Staged large-run pattern:

`run-chunked` is already an orchestrated command, so there is no separate `prepare -> run-plugin -> merge` chain for the whole dataset. The closest staged workflow is:

1. run the same config with smaller `chunk-size` and `workers` first
2. inspect the final merged output
3. rerun with the production chunk size and worker count

Example dry run:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --workers 2
```

If you need full manual staging, use the chunk YAML workflow in [chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md) instead.

What this does:

- reads one large `input_dir`
- splits the structures into temporary chunks
- runs chunks in parallel
- merges the final chunk outputs into the configured `out_dir`
- runs dataset analysis once on the merged result
- removes the temporary chunk workspace

In this mode, chunk parallelism happens inside the single `run-chunked` command
through `--workers`.

Parallelism model summary:

- `large_run`
  single scheduler job, internal parallelism through `--workers`
- `chunk_run`
  many scheduler jobs, one per manual chunk

- `plan-chunks` + `merge-planned-chunks`
  scheduler-managed chunk jobs generated automatically from one large config

The example YAML includes the broader built-in manipulation/plugin/dataset-analysis inventory as commented alternatives so you can promote or trim features without looking them up elsewhere.

If you enable antibody numbering roles together with `interface_contacts`, the merged `interfaces.parquet` will also contain per-CDR contact counts and residue lists for the numbered antibody/VHH roles.

Start with smaller values if you are unsure:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --workers 2
```

Slurm example:

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

This Slurm example does not submit one job per chunk.

It submits one job that gives `run-chunked` enough resources to schedule several
chunk workers internally.

Slurm array example for planned chunks:

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

Merge the planned chunks after the array finishes:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge-planned-chunks \
  --plan-dir /home/eva/minimum_atomworks/out_antibody_antigen_chunk_plan
```

Slurm dry-run example:

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-large-dryrun
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --workers 2
EOF
```

If you want Slurm to parallelize chunks as separate jobs instead, either:

- use the manual chunk workflow in [chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md), or
- use `plan-chunks` to generate scheduler-ready chunk configs automatically from one large config
