# HPC Slurm Guide

`minimum_atw` can now submit chunked Slurm runs from one command.

Use the same YAML for both CPU and GPU work. The planner decides whether the run is best submitted as:

- one mixed chunk job that requests CPU and GPU in the same allocation
- staged CPU-only and GPU-enabled jobs with Slurm dependencies between them

The command is `submit-slurm`.

## What `submit-slurm` does

`submit-slurm` can either:

- create a fresh chunk plan, then submit it
- reuse an existing `chunk_plan.json`, then submit it

It writes these files under `plan_dir`:

- `chunk_plan.json`: chunk configs plus CPU/GPU scheduler metadata
- `chunk_config_manifest.txt`: one chunk config path per line for Slurm arrays
- `slurm_scripts/`: generated array and merge scripts
- `slurm_submission.json`: submitted job IDs, dependencies, and script paths

Use `--dry-run` first if you want to inspect the generated scripts without calling `sbatch`.

## 1. One mixed chunk job

Use this when:

- you want the simplest operational path
- or `chunk_plan.json -> resource_plan.submission_plan.recommended_mode` is `single_job`

Example:

```bash
PYTHON=/home/eva/miniconda3/envs/atw_pp/bin/python
WORKDIR=/home/eva/minimum_atomworks
CONFIG=$WORKDIR/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml
PLAN_DIR=/path/to/your/chunk_plan

cd "$WORKDIR"

$PYTHON -m minimum_atw.cli submit-slurm \
  --config "$CONFIG" \
  --chunk-size 50 \
  --plan-dir "$PLAN_DIR" \
  --mode mixed \
  --sbatch-common-arg=--account=my_lab \
  --sbatch-mixed-arg=--partition=gpu \
  --sbatch-mixed-arg=--mem=48G \
  --sbatch-mixed-arg=--time=08:00:00 \
  --sbatch-merge-arg=--partition=cpu \
  --sbatch-merge-arg=--mem=32G \
  --sbatch-merge-arg=--time=02:00:00
```

This submits:

- one Slurm array job running `minimum_atw.cli run --config "$CONFIG"` for each chunk
- one dependent CPU-only `merge-planned-chunks` job

## 2. Split CPU-stage and GPU-stage jobs automatically

Use this when:

- `recommended_mode` is `split_by_stage`
- you do not want GPU nodes held during CPU-only phases

Example:

```bash
PYTHON=/home/eva/miniconda3/envs/atw_pp/bin/python
WORKDIR=/home/eva/minimum_atomworks
CONFIG=$WORKDIR/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml
PLAN_DIR=/path/to/your/chunk_plan

cd "$WORKDIR"

$PYTHON -m minimum_atw.cli submit-slurm \
  --config "$CONFIG" \
  --chunk-size 50 \
  --plan-dir "$PLAN_DIR" \
  --mode staged \
  --sbatch-common-arg=--account=my_lab \
  --sbatch-cpu-arg=--partition=cpu \
  --sbatch-cpu-arg=--mem=32G \
  --sbatch-cpu-arg=--time=04:00:00 \
  --sbatch-gpu-arg=--partition=gpu \
  --sbatch-gpu-arg=--mem=32G \
  --sbatch-gpu-arg=--time=04:00:00 \
  --sbatch-merge-arg=--partition=cpu \
  --sbatch-merge-arg=--mem=32G \
  --sbatch-merge-arg=--time=02:00:00
```

This submits, in order:

- `prepare` chunk array on CPU nodes
- one array per planned CPU or GPU plugin stage from `resource_plan.submission_plan.stages`
- `merge` chunk array on CPU nodes
- `analyze-dataset` chunk array if `dataset_analysis_mode` is `per_chunk` or `both`
- one dependent CPU-only `merge-planned-chunks` job

If a stage has both a CPU job and a GPU job, they are submitted as separate jobs with the same upstream dependency and can run in parallel.

## 3. Auto mode

`--mode auto` is the default.

Example:

```bash
$PYTHON -m minimum_atw.cli submit-slurm \
  --config "$CONFIG" \
  --chunk-size 50 \
  --plan-dir "$PLAN_DIR" \
  --mode auto \
  --sbatch-common-arg=--account=my_lab \
  --sbatch-cpu-arg=--partition=cpu \
  --sbatch-gpu-arg=--partition=gpu \
  --sbatch-merge-arg=--partition=cpu
```

In `auto` mode:

- `cpu_only` and `single_job` plans submit as mixed jobs
- `split_by_stage` plans submit as staged CPU/GPU jobs

## 4. Reuse an existing plan

If you already ran `plan-chunks`, reuse it:

```bash
$PYTHON -m minimum_atw.cli submit-slurm \
  --plan-dir "$PLAN_DIR" \
  --reuse-plan \
  --mode auto \
  --sbatch-common-arg=--account=my_lab \
  --sbatch-cpu-arg=--partition=cpu \
  --sbatch-gpu-arg=--partition=gpu \
  --sbatch-merge-arg=--partition=cpu
```

## 5. Dry-run first

Use this to generate the scripts and dependency graph without submitting anything:

```bash
$PYTHON -m minimum_atw.cli submit-slurm \
  --config "$CONFIG" \
  --chunk-size 50 \
  --plan-dir "$PLAN_DIR" \
  --mode auto \
  --dry-run
```

Then inspect:

- `plan_dir/slurm_scripts/*.sh`
- `plan_dir/slurm_submission.json`

## Notes

- Slurm still decides placement. `minimum_atw` does not allocate resources beyond what your `sbatch` arguments request.
- GPU stages still need CPU threads. The planner already records both.
- The staged submission graph follows `chunk_plan.json -> resource_plan.submission_plan.stages` exactly.
- Manual Slurm submission is still possible if you want to customize the job graph beyond what the built-in backend does.
