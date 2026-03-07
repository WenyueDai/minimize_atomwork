# Multi-Dataset Comparison Example

This folder shows the closest current workflow to:

- compare paratope / epitope clusters within each dataset
- compare clusters across datasets
- compare aggregate interface properties across datasets

## What the current code supports

1. Run each dataset separately with `cluster` enabled.
2. Inspect each dataset's own `pdb.parquet` for within-dataset cluster labels.
3. Merge multiple finished `out_dir` results with `merge-datasets`.
4. Run `analyze-dataset` on the merged output to compute cross-dataset clustering on the pooled interfaces.
5. If you want all downstream calculations to use aligned coordinates, enable `superimpose_to_reference` during prepare and let clustering use the aligned prepared structures automatically.

## Important limitation

`reference_dataset_dir` exists in config, but none of the built-in dataset analyses currently use `ctx.reference_grains`.
So the built-in way to compare datasets today is:

- separate runs for per-dataset analysis
- a merged run for pooled cross-dataset analysis

It is not yet a true "dataset A versus dataset B" differential analysis mode.

## Recommended workflow

Dataset A:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/multi_dataset/dataset_a_antibody_antigen.yaml
```

Dataset B:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/multi_dataset/dataset_b_antibody_antigen.yaml
```

Merge them:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge-datasets \
  --out-dir /home/eva/minimum_atomworks/out_compare_ab \
  --source-out-dir /home/eva/minimum_atomworks/out_dataset_a \
  --source-out-dir /home/eva/minimum_atomworks/out_dataset_b
```

Analyze the merged output:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli analyze-dataset \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/multi_dataset/compare_merged_datasets.yaml
```

## Step By Step: What This Multi-Dataset Workflow Does

Using [dataset_a_antibody_antigen.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/multi_dataset/dataset_a_antibody_antigen.yaml), [dataset_b_antibody_antigen.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/multi_dataset/dataset_b_antibody_antigen.yaml), and [compare_merged_datasets.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/multi_dataset/compare_merged_datasets.yaml).

### Step 1 — Run dataset A end-to-end

`run_pipeline(cfg_a)` executes the full PREPARE → EXECUTE → MERGE → DATASET ANALYSIS sequence on dataset A's structures in isolation.

During **PREPARE**, each structure is loaded into a biotite `AtomArray`, QC units run (`chain_continuity`, `structure_clashes`), then structure manipulation units run (`center_on_origin`, `superimpose_to_reference`). `superimpose_to_reference` mutates `ctx.aa` in place — all downstream plugins for this run will see the aligned coordinates. The transformed structure is saved to `_prepared/structures/<name>.bcif` and `prepared__path` is recorded in `_prepared/pdb.parquet`.

During **EXECUTE**, each `pdb_calculation` plugin reads the prepared aligned structure, calls `available(ctx)` to decide whether to run, and yields prefixed column rows accumulated in a `TableBuffer`. Each plugin writes its output to `_plugins/<name>/pdb.parquet`.

During **MERGE**, `merge_outputs(cfg_a)` LEFT JOINs each plugin's output onto the prepare-stage base rows. The result is `out_dataset_a/pdb.parquet` — a single wide table with every QC, manipulation, and plugin column side-by-side. All base rows are preserved; plugins that skipped a structure contribute `NaN`.

During **DATASET ANALYSIS**, `analyze_dataset_outputs(out_dataset_a)` reads the merged `pdb.parquet`, filters by `grain`, and runs:
- `interface_summary` and `cdr_entropy` — write aggregate rows to `out_dataset_a/dataset.parquet`.
- `cluster` with job names like `within_dataset_paratope` and `within_dataset_epitope` — reloads Cα coordinates from `prepared__path` (aligned coordinates), computes RMSD clusters on the within-dataset interface population, writes `cluster__within_dataset_paratope_cluster_id` etc. back onto `out_dataset_a/pdb.parquet`.

### Step 2 — Run dataset B end-to-end

Identical to Step 1 but using `cfg_b`. Dataset B gets its own `out_dataset_b/pdb.parquet` with its own within-dataset cluster labels. The two runs are fully independent and can execute in parallel.

### Step 3 — `merge-datasets` stacks the two outputs (STACK, not JOIN)

`merge_dataset_outputs([out_dataset_a, out_dataset_b], out_compare_ab)` is a **row-union** operation:

1. Reads `run_metadata.json` from each source to validate merge compatibility. The compatibility check compares roles, interface pairs, assembly_id mode, and plugin set. Mismatched sources are rejected before any stacking.
2. Concatenates `pdb.parquet` row-wise. Global identity key uniqueness (`path` + `assembly_id` + `grain` + grain-specific keys) is enforced across the combined dataset.
3. Preserves `dataset__id` and `dataset__name` on every row — columns originally set via `dataset_annotations.dataset_id` and `dataset_annotations.dataset_name` in each source config. This is the only provenance information that survives into `pdb.parquet`; all other `dataset_annotations` keys go into `dataset.parquet` via the `dataset_annotations` analysis.
4. Writes `out_compare_ab/pdb.parquet`, `plugin_status.parquet`, `bad_files.parquet`, and `dataset_metadata.json`.

The merged `pdb.parquet` contains both datasets' `within_dataset_*` cluster columns from Steps 1 and 2, but those per-dataset cluster IDs are **not** comparable across datasets — cluster `0` from dataset A has no relationship to cluster `0` from dataset B.

### Step 4 — `analyze-dataset` on the merged output for cross-dataset clusters

`analyze_dataset_outputs(out_compare_ab, cfg=compare_merged_datasets_cfg)` reads the full merged `pdb.parquet` and runs the analyses configured in `compare_merged_datasets.yaml`:

- `cluster` with job names like `cross_dataset_paratope` and `cross_dataset_epitope` — reloads Cα coordinates from each row's `prepared__path` (which points into the source dataset's `_prepared/` directory), computes RMSD clusters on the **pooled** interface population from both datasets, and writes `cluster__cross_dataset_paratope_cluster_id` etc. back onto `out_compare_ab/pdb.parquet`.
- `interface_summary` aggregates counts across the pooled dataset.
- `cdr_entropy` computes entropy over the pooled sequence distribution.

Because each row's `prepared__path` still points into `out_dataset_a/_prepared/` or `out_dataset_b/_prepared/`, the cross-dataset cluster plugin can reload the original aligned prepared structures as long as those `_prepared/` directories still exist.

After this step, the merged `pdb.parquet` contains both within-dataset cluster columns (from Steps 1–2) and cross-dataset cluster columns (from Step 4). You can filter by `dataset__id` to separate the two populations, or use the cross-dataset cluster IDs to find structurally similar interfaces that appear in both campaigns.

### What Persists

- Dataset A and B each keep their own `_prepared/` directories. These must remain accessible for the cross-dataset cluster analysis in Step 4 to reload aligned structures through `prepared__path`.
- If you enable `cleanup_prepared_after_dataset_analysis: true` on the source runs, those `_prepared/` directories are deleted after their own dataset analysis succeeds. This makes later cross-dataset re-analysis from aligned prepared structures impossible.
- The merged output directory (`out_compare_ab`) does not have a `_prepared/` cache of its own. If you need to run `analyze-dataset` again on the merged output and the source `_prepared/` directories are gone, clustering will fall back to unaligned coordinates or fail, depending on mode.

## How to read the outputs

- Within each dataset:
  inspect each dataset's `pdb.parquet` and look at `cluster__within_dataset_paratope_*` and `cluster__within_dataset_epitope_*` on `grain == "interface"` rows.
- Across datasets:
  inspect the merged `pdb.parquet` after `analyze-dataset`; `cluster__cross_dataset_paratope_*` and `cluster__cross_dataset_epitope_*` were computed on the pooled interface set.
- Aggregate comparison:
  inspect merged `dataset.parquet` for `interface_summary` rows.
- Superposition outputs:
  inspect `sup__shared_atoms_rmsd` and `sup__rmsd`. For prepare-stage superposition, `sup__coordinates_applied = true` means the saved prepared coordinates were rewritten and later clustering can reload those aligned structures through `prepared__path`.

Merged `pdb.parquet` keeps only `dataset__id` and `dataset__name` as dataset-level provenance columns. Any other `dataset_annotations` keys stay in `dataset.parquet` via the `dataset_annotations` analysis instead of being copied onto every PDB row.

## Practical note

For a clean between-dataset comparison, make sure both source datasets use the same:

- `roles`
- `interface_pairs`
- `numbering_roles`
- `numbering_scheme`
- core interface plugins such as `interface_contacts` and `interface_metrics`

Otherwise the merged outputs may still stack, but the comparisons will be less meaningful.

For cross-dataset clustering in a common structural frame, enable prepare-stage superposition in each source run and anchor only on the antigen. In an antibody-antigen complex with antigen `A` and antibody `B+C`, that means using a reference structure containing only chain `A` and setting:

```yaml
manipulations:
  - name: "superimpose_to_reference"
    grain: "pdb"

plugin_params:
  superimpose_to_reference:
    reference_path: "/path/to/antigen_chain_A_only_reference.pdb"
    on_chains: ["A"]
```

That rewrites the coordinates during prepare. The aligned prepared structures are preserved automatically so merged dataset analyses can reload them later.

Use either the prepare-stage manipulation or the plugin-stage superposition in a given run, not both. The prepare-stage path is the recommended one for cross-dataset work.

The source-dataset and merged-dataset cluster jobs intentionally use different names so both sets of cluster labels can coexist in the final merged `pdb.parquet`.

## Files

- [dataset_a_antibody_antigen.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/multi_dataset/dataset_a_antibody_antigen.yaml)
- [dataset_b_antibody_antigen.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/multi_dataset/dataset_b_antibody_antigen.yaml)
- [compare_merged_datasets.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/multi_dataset/compare_merged_datasets.yaml)
