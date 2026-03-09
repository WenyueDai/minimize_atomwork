# HPC Slurm Guide

`minimum_atw` can now submit chunked Slurm runs from one command.

Use the same YAML for both CPU and GPU work. The planner decides whether the run is best submitted as:

- one mixed chunk job that requests CPU and GPU in the same allocation
- staged CPU-only and GPU-enabled jobs with Slurm dependencies between them

The command is `submit-slurm`.

Recommended usage:

1. put `slurm.chunk_size` and your cluster-specific `sbatch_*` args into the YAML
2. run `python -m minimum_atw.cli submit-slurm --config your.yaml`
3. let the planner decide whether the job graph should stay mixed or split into CPU and GPU stages

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
If `slurm.plan_dir` is omitted, `submit-slurm` derives `plan_dir` as `<out_dir>_plan`.

## 1. One mixed chunk job

Use this when:

- you want the simplest operational path
- or `chunk_plan.json -> resource_plan.submission_plan.recommended_mode` is `single_job`

Example YAML block:

```yaml
slurm:
  chunk_size: 50
  # plan_dir: "/path/to/your/out_antibody_antigen_chunked_plan"
  sbatch_common_args:
    - "--account=my_lab"
  sbatch_mixed_args:
    - "--partition=gpu"
    - "--mem=48G"
    - "--time=08:00:00"
  sbatch_merge_args:
    - "--partition=cpu"
    - "--mem=32G"
    - "--time=02:00:00"
```

Command:

```bash
PYTHON=$(which python)  # activate atw_pp env first: conda activate atw_pp
WORKDIR=/path/to/repo
CONFIG=$WORKDIR/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml

cd "$WORKDIR"

$PYTHON -m minimum_atw.cli submit-slurm \
  --config "$CONFIG" \
  --dry-run
```

This submits:

- one Slurm array job running `minimum_atw.cli run --config "$CONFIG"` for each chunk
- one dependent CPU-only `merge-planned-chunks` job

## 2. Split CPU-stage and GPU-stage jobs automatically

Use this when:

- `recommended_mode` is `split_by_stage`
- you do not want GPU nodes held during CPU-only phases

Example YAML block:

```yaml
slurm:
  chunk_size: 50
  # plan_dir: "/path/to/your/out_antibody_antigen_chunked_plan"
  mode: "staged"
  sbatch_common_args:
    - "--account=my_lab"
  sbatch_cpu_args:
    - "--partition=cpu"
    - "--mem=32G"
    - "--time=04:00:00"
  sbatch_gpu_args:
    - "--partition=gpu"
    - "--mem=32G"
    - "--time=04:00:00"
  sbatch_merge_args:
    - "--partition=cpu"
    - "--mem=32G"
    - "--time=02:00:00"
```

Command:

```bash
PYTHON=$(which python)  # activate atw_pp env first: conda activate atw_pp
WORKDIR=/path/to/repo
CONFIG=$WORKDIR/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml

cd "$WORKDIR"

$PYTHON -m minimum_atw.cli submit-slurm \
  --config "$CONFIG" \
  --dry-run
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
  --dry-run
```

In `auto` mode:

- `cpu_only` and `single_job` plans submit as mixed jobs
- `split_by_stage` plans submit as staged CPU/GPU jobs

## 4. Reuse an existing plan

If you already ran `plan-chunks`, or already called `submit-slurm --dry-run`, reuse that plan directory:

```bash
$PYTHON -m minimum_atw.cli submit-slurm \
  --plan-dir "$PLAN_DIR" \
  --reuse-plan \
  --dry-run
```

## 5. Dry-run first

Use this to generate the scripts and dependency graph without submitting anything:

```bash
$PYTHON -m minimum_atw.cli submit-slurm \
  --config "$CONFIG" \
  --dry-run
```

Then inspect:

- `plan_dir/slurm_scripts/*.sh`
- `plan_dir/slurm_submission.json`

## Notes

- Slurm still decides placement. `minimum_atw` does not allocate resources beyond what your `sbatch` arguments request.
- CLI flags such as `--mode`, `--chunk-size`, `--plan-dir`, and `--sbatch-*` remain available as expert overrides, but they are no longer required for the normal workflow.
- GPU stages still need CPU threads. The planner already records both.
- The staged submission graph follows `chunk_plan.json -> resource_plan.submission_plan.stages` exactly.
- Manual Slurm submission is still possible if you want to customize the job graph beyond what the built-in backend does.
