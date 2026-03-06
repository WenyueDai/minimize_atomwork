# Large Run Example

This folder is for large datasets (50+ structures).

Use it if:

- you want automatic chunking with `run-chunked`
- you want one larger job with internal parallel workers
- or you want `plan-chunks` to generate scheduler-ready chunk configs for a Slurm array
- **you are running Rosetta on many structures and need efficient memory/CPU usage**

## File

- `example_antibody_antigen_chunked.yaml` (includes Rosetta by default)

## Rosetta Resource Management

Rosetta InterfaceAnalyzer is computationally expensive (~5-30s per interface pair). For large datasets:

| Dataset Size | Recommended Strategy | Est. Total Time | Resources |
|--------------|----------------------|-----------------|-----------|
| 10-50 structures | `run-chunked` with 2-4 workers | 1-5 hours | 4-8 CPU, 16-32 GB |
| 50-500 structures | `plan-chunks` + Slurm array | 30 mins - 2 hours | 4-8 CPU per chunk job |
| 500+ structures | `plan-chunks` + array + many workers | depends on queue | Distributed across nodes |

**Key insight:** Chunking allows parallel Rosetta execution. Each chunk runs Rosetta independently, so N workers can run N structures simultaneously (vs. serial: 100 structures × 20s = 33 minutes).

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

## Chunking Strategy for Rosetta

**Recommended chunk sizes:**
- Structures with 1 interface pair: `--chunk-size 10-20`
- Structures with 2-3 interface pairs: `--chunk-size 5-10`
- Structures with 4+ interface pairs: `--chunk-size 2-5`

Reasoning: Each Rosetta call takes 5-30 seconds. Larger chunks = fewer chunk jobs but longer per-job runtime.

**Worker allocation:**
- Small cluster (1 node): `--workers 2-4`
- Medium cluster (1-2 nodes): `--workers 4-8`
- Large cluster: `--workers 8-16` (or rely on array jobs)

**Memory per worker:**
- Rosetta + Python overhead: ~200-500 MB per worker
- Set `#SBATCH --mem-per-cpu=4G` for 2-4 worker jobs

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
