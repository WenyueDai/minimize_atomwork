# Chunk Run Examples

This folder is for manual chunk configs: one config per chunk, one run per config, then an explicit merge.
Each chunk writes its own `run_metadata.json`, so you can inspect one pilot chunk before submitting the full array.
If you want automatic chunk planning and one-command Slurm submission, use the [large_run](../large_run/README.md) examples with `submit-slurm` instead.

## Files

- [chunk_antibody_antigen_01.yaml](minimum_atw/examples/input/chunk_run/chunk_antibody_antigen_01.yaml)
- [chunk_antibody_antigen_02.yaml](minimum_atw/examples/input/chunk_run/chunk_antibody_antigen_02.yaml)
- [chunk_config_manifest_example.txt](minimum_atw/examples/input/chunk_run/chunk_config_manifest_example.txt)

## Run the chunks

Activate the conda environment first (required for real-time progress output):

```bash
conda activate atw_pp
```

Then run each chunk from the repo root:

```bash
python -m minimum_atw.cli run \
  --config minimum_atw/examples/input/chunk_run/chunk_antibody_antigen_01.yaml

python -m minimum_atw.cli run \
  --config minimum_atw/examples/input/chunk_run/chunk_antibody_antigen_02.yaml
```

## Merge the finished chunks

```bash
python -m minimum_atw.cli merge-datasets \
  --out-dir /path/to/out_antibody_antigen_merged \
  --source-out-dir /path/to/out_chunk_antibody_antigen_01 \
  --source-out-dir /path/to/out_chunk_antibody_antigen_02
```

## Step By Step: What This Manual Chunk Workflow Does

Using [chunk_antibody_antigen_01.yaml](minimum_atw/examples/input/chunk_run/chunk_antibody_antigen_01.yaml) and [chunk_antibody_antigen_02.yaml](minimum_atw/examples/input/chunk_run/chunk_antibody_antigen_02.yaml):

### Step 1 — You define the chunk boundaries

You decide which structures go into each chunk and write one YAML config per chunk.
Each YAML is a complete, independent pipeline config pointing at its own `input_dir` and `out_dir`.
There is no shared state between chunks at runtime — they are fully isolated processes.

### Step 2 — `run` invokes a full single-dataset pipeline per chunk

Each `minimum-atw run --config chunk_N.yaml` call invokes `run_pipeline(cfg)` internally.
That function executes four stages in order: **PREPARE → EXECUTE → MERGE → DATASET ANALYSIS**.
The chunk does not know it is part of a larger dataset — it simply processes its own inputs end to end.
The resulting `run_metadata.json` also records `plugin_execution.scheduler_resources.single_job` and `plugin_execution.scheduler_resources.submission_plan` for that chunk.

### Step 3 — PREPARE stage: QC, manipulation, and cache write

`prepare_outputs(cfg)` iterates over every structure in `input_dir` and for each one:

1. Loads the structure into a biotite `AtomArray` and builds `Context(aa, chains, roles, config)`.
2. Runs **quality control** units in order (`prepare_section='quality_control'`):
   - `chain_continuity` — checks residue-ID gaps and backbone breaks per chain;
     writes `continuity__n_breaks`, `continuity__has_break` rows to the prepare table.
   - `structure_clashes` — counts steric clashes between heavy atoms;
     writes `clash__has_clash`, `clash__n_clashing_atom_pairs`, `clash__n_clashing_atoms`.
3. Runs **structure manipulation** units in order (`prepare_section='structure'`):
   - `center_on_origin` — translates `ctx.aa` so its centroid is at the origin;
     records `center__centroid_x/y/z` (the pre-translation centroid) and calls `ctx.rebuild_views()`.
   - `superimpose_to_reference` — fits `ctx.aa` onto the first structure seen (or a fixed reference path);
     mutates `ctx.aa` in place, calls `ctx.rebuild_views()`, and records `sup__shared_atoms_rmsd`,
     `sup__anchor_atoms`, `sup__alignment_method`, `sup__coordinates_applied` per structure plus
     `sup__rmsd`, `sup__matched_atoms` per chain.
4. Saves the transformed `ctx.aa` to `_prepared/structures/<name>.bcif`.
5. After all structures, writes:
   - `_prepared/pdb.parquet` — unified table with a `grain` column (structure / chain) holding all QC and manipulation output rows.
   - `_prepared/prepared_manifest.parquet` — maps each `source_path` to its `prepared_path`.
   - `_prepared/bad_files.parquet` — any structures that failed to load or were rejected by QC.

`_prepared/` is a **cache boundary**: if it already exists and is complete, subsequent plugin runs read from it without re-running prepare.

### Step 4 — EXECUTE stage: plugins read from cache, write per-plugin tables

`run_plugins(cfg, plugin_names)` loads `prepared_manifest.parquet`, then for each structure in the manifest:

1. Reads the prepared structure from `_prepared/structures/`.
2. Rebuilds `Context(aa, chains, roles, config)` from the cached file.
3. Runs each configured `pdb_calculation` plugin sequentially. Each chunk still plans CPU and GPU pools before dispatch, so a pilot chunk tells you the exact resource shape of the full array job. Each plugin:
   - Calls `available(ctx)` first; skips the structure if `False`.
   - Yields one dict per grain row (`grain`, identity key columns, then `prefix__column` output columns).
   - Rows accumulate in a `TableBuffer` (spills to disk if memory threshold is crossed).
4. After all structures, each plugin flushes its buffer to `_plugins/<name>/pdb.parquet`.

All plugin output columns are namespaced by `prefix` (e.g. `iface__n_contacts`, `ifm__left_n_interface_residues`).
No two registered plugins may share a prefix — the registry rejects collisions at load time.

### Step 5 — MERGE stage: LEFT JOIN plugins onto base rows

`merge_outputs(cfg)` produces the final per-chunk `pdb.parquet`:

1. Reads `_prepared/pdb.parquet` as the **base** (one row per structure/chain/role/interface per QC/manipulation plugin).
2. For each plugin in `_plugins/`, reads that plugin's `pdb.parquet` and LEFT JOINs it onto the base using the identity key columns (`path`, `assembly_id`, `grain`, and `chain_id` / `role` / `pair` as applicable).
3. Any structure the plugin skipped (via `available()`) gets `NaN` for that plugin's columns — the base row is always preserved.
4. Writes the merged result to `out_dir/pdb.parquet` plus `plugin_status.parquet` (which plugins ran and on how many rows) and `bad_files.parquet`.

After this step, `out_dir/pdb.parquet` is a single wide table: every row has identity columns, every QC/manipulation column, and every plugin column side-by-side.

### Step 6 — DATASET ANALYSIS stage (per-chunk, because `dataset_analysis_mode: per_chunk`)

`analyze_dataset_outputs(out_dir)` reads `out_dir/pdb.parquet`, filters rows by `grain`, and runs each configured `dataset_calculation` plugin:

- `interface_summary` — counts interfaces and unique sequences per pair; writes aggregate rows to `dataset.parquet`.
- `cdr_entropy` — computes position-wise Shannon entropy for numbered CDR residues per role and region; if `sequence` is selected it writes sequence-level summary rows to `dataset.parquet`.
- `cluster` — reads interface residue columns, extracts Cα coordinates of interface residues, and computes pairwise Chamfer-distance clusters. **Writes cluster labels back onto `out_dir/pdb.parquet`** (not into `dataset.parquet`). Clustering now runs only when `dataset_analysis_params.cluster.mode` is set explicitly. With `mode` set and no `interface_side`, two default jobs are created, producing `cluster__left_*` and `cluster__right_*` columns. To get separate named columns per side, define explicit jobs under `dataset_analysis_params.cluster.jobs` (see below).

Because this runs per-chunk, entropy and cluster labels reflect only the structures in that chunk — not the full dataset.

### Step 7 — `merge-datasets` stacks chunk outputs (STACK, not JOIN)

`merge_dataset_outputs([chunk_out_dirs], merged_out_dir)` is a **row-union** operation, not a column-join:

1. Reads `run_metadata.json` from each chunk to verify merge compatibility (same roles, interface pairs, assembly_id mode, and plugin set). Rejects mismatched chunks.
2. Concatenates each chunk's `pdb.parquet` row-wise. Identity key uniqueness across the combined dataset is enforced.
3. Assigns global `dataset__id` and `dataset__name` columns derived from the chunk source directories.
4. Writes `merged_out_dir/pdb.parquet`, `plugin_status.parquet`, `bad_files.parquet`, and `dataset_metadata.json`.

The merged `pdb.parquet` will carry the per-chunk cluster labels from Step 6, but those labels are **not** globally consistent — cluster `1` in chunk 01 and cluster `1` in chunk 02 are independent clusters.

### Step 8 — Optional: recompute whole-dataset clusters

Run `analyze-dataset` with a config whose `out_dir` points at the merged output.
The simplest way is to start from one of the chunk YAMLs and change only `out_dir` plus any dataset-analysis settings you want for the merged run.

Example merged-output config:

```bash
python -m minimum_atw.cli analyze-dataset \
  --config /path/to/your/chunk_antibody_antigen_merged.yaml
```

This re-runs `analyze_dataset_outputs()` on the full merged `pdb.parquet`. The `cluster` plugin will now see all structures together and produce globally consistent cluster labels, overwriting the per-chunk ones. This merged re-analysis step is CPU-only in the built-in examples.

### What Persists

- Each chunk keeps its own `_prepared/` directory by default. This is the prepare cache — reusable across plugin re-runs without re-doing QC or superimposition.
- The merged output does not automatically get a merged `_prepared/` cache. If you want to run new plugins on the merged dataset, you must re-prepare from scratch or re-run per-chunk.
- If you enable `cleanup_prepared_after_dataset_analysis: true` in a chunk YAML, that chunk's `_prepared/` directory is removed only after its dataset analysis succeeds. Useful on storage-constrained clusters.

## What these YAMLs show

- explicit manual chunk outputs
- `dataset_analysis_mode: per_chunk`
- optional checkpoint settings
- optional Rosetta scaffold
- optional `cdr_entropy`
- enabled interface clustering

See [../README.md](minimum_atw/examples/README.md) for the field-by-field glossary and when to turn each option on or off.

Clustering note:

- These chunk YAMLs enable `cluster`, so they write per-chunk cluster labels onto interface rows in each chunk's `pdb.parquet`.
- If you want biologically meaningful whole-dataset clusters, merge first and then run `analyze-dataset` on the merged output with a config that enables `cluster`.

Cluster behavior in the chunk examples:

```yaml
dataset_analyses:
  - "cluster"
```

With `mode: "absolute_interface_ca"` and no `interface_side`, **two jobs** are created automatically — one per interface side — using `distance_threshold: 2.0` Å. Output columns: `cluster__left_cluster_id`, `cluster__left_cluster_size`, `cluster__right_cluster_id`, `cluster__right_cluster_size` (plus `_representative_path`, `_distance_to_representative`, `_n_points`).

**Two clustering modes:**

| Mode | Question answered | Requires |
|------|-------------------|----------|
| `absolute_interface_ca` | *Where* does it bind? — binding site on the antigen | `superimpose_to_reference` in prepare |
| `shape_interface_ca` | *How* does it bind? — geometry of the interface | any prepare stage |

`absolute_interface_ca` uses absolute Cα positions from the globally superimposed structures. Two antibodies binding different epitopes land in different clusters even if their binding shapes look similar.

`shape_interface_ca` locally superimposes the interface Cα (Kabsch algorithm on common residues), then computes Chamfer distance. Two antibodies with the same binding geometry cluster together regardless of where on the antigen they bind.

If the default threshold is too tight (each structure ends up in its own singleton cluster), increase `distance_threshold`:

```yaml
dataset_analysis_params:
  cluster:
    mode: "absolute_interface_ca"
    distance_threshold: 5.0   # Å — loosen to merge more structures
```

To run multiple named jobs (e.g. site and shape for the epitope side):

```yaml
dataset_analysis_params:
  cluster:
    jobs:
      - name: "epitope_site"
        interface_side: "right"
        mode: "absolute_interface_ca"
        distance_threshold: 5.0
      - name: "epitope_shape"
        interface_side: "right"
        mode: "shape_interface_ca"
        distance_threshold: 3.0
```

This produces `cluster__epitope_site_cluster_id` and `cluster__epitope_shape_cluster_id` columns.

## Scheduler pattern

This section is for the manual chunk workflow in this folder. If you want the framework to generate Slurm scripts and dependencies for you, use `minimum_atw.cli submit-slurm` from [large_run/HPC_SLURM_GUIDE.md](../large_run/HPC_SLURM_GUIDE.md).

```bash
MANIFEST=minimum_atw/examples/input/chunk_run/chunk_config_manifest_example.txt
```

Generic array-job pattern:

```bash
sbatch --array=1-3 <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1          # only when the chunk's submission_plan includes a gpu job class
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%A_%a.out
set -euo pipefail

cd /path/to/repo
conda activate atw_pp

MANIFEST=/path/to/chunk_config_manifest.txt
CONFIG=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$MANIFEST")

python -m minimum_atw.cli run --config "$CONFIG"
EOF
```

Scheduler note:

- For CPU-only chunk configs, request the counts from `run_metadata.json -> plugin_execution.scheduler_resources.single_job`.
- For mixed CPU/GPU chunk configs, prefer `run_metadata.json -> plugin_execution.scheduler_resources.submission_plan.job_classes` so you can decide whether to keep one mixed job shape or split CPU-only and GPU-enabled stages across different node types.
