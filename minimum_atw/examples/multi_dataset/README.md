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

Using [dataset_a_antibody_antigen.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/multi_dataset/dataset_a_antibody_antigen.yaml), [dataset_b_antibody_antigen.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/multi_dataset/dataset_b_antibody_antigen.yaml), and [compare_merged_datasets.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/multi_dataset/compare_merged_datasets.yaml):

1. Run dataset A. It performs a normal pipeline run on dataset A only.
2. During `prepare`, it aligns each structure with `superimpose_to_reference`, so downstream calculations use aligned coordinates.
3. The aligned prepared structures are saved under dataset A's `_prepared/`.
4. The plugins run on those aligned structures and write dataset A's `pdb.parquet`.
5. Post-merge dataset analyses for dataset A write within-dataset cluster labels such as `cluster__within_dataset_paratope_*`.
6. Run dataset B the same way.
7. `merge-datasets` then stacks the finished dataset A and dataset B outputs into one pooled `out_dir`.
8. The merged output preserves `dataset__id` and `dataset__name` on every `pdb.parquet` row so you can tell which dataset each interface came from.
9. `analyze-dataset` on the merged output runs the cross-dataset cluster jobs from `compare_merged_datasets.yaml`.
10. Those merged cluster jobs write new labels such as `cluster__cross_dataset_paratope_*` back onto the merged `pdb.parquet`.
11. Because the source runs used prepare-stage superposition, `cluster.mode: interface_ca` on the merged run can reload the aligned prepared structures through `prepared__path`.

### What Persists

- Dataset A and dataset B each keep their own `_prepared/` directory by default.
- Those prepared caches are what let later merged dataset analysis reuse aligned coordinates.
- If you enable `cleanup_prepared_after_dataset_analysis: true` on the source dataset runs, those source `_prepared/` directories are deleted after successful dataset analysis, which means later merged re-analysis from aligned prepared structures will no longer be possible.

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
