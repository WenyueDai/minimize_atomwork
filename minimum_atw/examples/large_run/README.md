# Large Run Examples

This folder is for chunk-aware workflows:

- `run-chunked`
- `plan-chunks`
- `merge-planned-chunks`

## Files

- [example_antibody_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml)
- [example_vhh_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_vhh_antigen_chunked.yaml)
- [example_protein_protein_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_protein_protein_chunked.yaml)

## Run with internal chunk workers

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --workers 2
```

## Plan chunk configs for a scheduler

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli plan-chunks \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --plan-dir /home/eva/minimum_atomworks/out_antibody_antigen_chunk_plan
```

## What these configs show

- chunk-aware prepare and plugin execution
- `dataset_analysis_mode: post_merge` by default
- optional checkpoint settings
- optional Rosetta scaffold
- optional `cdr_entropy`
- enabled interface clustering

See [../README.md](/home/eva/minimum_atomworks/minimum_atw/examples/README.md) for the field glossary and flag guidance.

## Step By Step: What `run-chunked` Does

Using [example_antibody_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml) as the reference:

1. The CLI loads the YAML into `Config`.
2. `input_dir` is scanned for `.pdb` and `.cif` files.
3. Those inputs are split into chunks of at most `--chunk-size` structures.
4. Each chunk runs as an ordinary pipeline run in its own temporary workspace.
5. Inside each chunk, `prepare` runs first:
   - load each structure
   - run `chain_continuity`
   - run `structure_clashes`
   - run `center_on_origin`
   - run `superimpose_to_reference`
6. Because `superimpose_to_reference` is in `manipulations`, the structure coordinates are rewritten during prepare before downstream plugins run.
7. The aligned prepared structure is saved under that chunk's `_prepared/structures`, and `prepared__path` is recorded in `pdb.parquet`.
8. The configured plugins then run on the already-aligned prepared structure:
   - `identity`
   - `chain_stats`
   - `role_sequences`
   - `role_stats`
   - `interface_contacts`
   - `interface_metrics`
   - `antibody_cdr_lengths`
   - `antibody_cdr_sequences`
   - `abepitope_score`
9. Each chunk writes its own final `pdb.parquet`, plus `_prepared/` outputs because aligned structures may be needed later.
10. After all chunks finish, `merge-datasets`-style stacking combines the chunk outputs into the final `out_dir`.
11. Because these large-run examples use `dataset_analysis_mode: post_merge`, dataset analyses run once on the merged output, not on each chunk.
12. `cluster` writes cluster labels back onto merged `grain == "interface"` rows in the final `pdb.parquet`.
13. Since prepare-stage superposition was used, normal `cluster.mode: interface_ca` reloads the aligned prepared structures via `prepared__path`, so clustering also uses aligned coordinates.
14. `dataset.parquet` is written with dataset-level analyses such as `dataset_annotations` and `interface_summary`.

### What Persists

- Final outputs stay in your configured `out_dir`.
- The aligned prepared structures stay under `out_dir/_prepared/` by default.
- The temporary per-chunk workspaces are deleted automatically when `run-chunked` finishes.
- If you set `cleanup_prepared_after_dataset_analysis: true`, the final `_prepared/` directory is deleted only after dataset analysis completes successfully.

Execution note:

- within each chunk, native `atom_array` plugins are batched together
- external or file-bound plugins such as `abepitope_score` and optional Rosetta run in isolated workers
- those execution groups can run concurrently inside the chunk run

Clustering behavior in the examples:

```yaml
dataset_analyses:
  - "cluster"
```

With no extra cluster params, chunked examples also emit both `left` and `right` jobs automatically.
Those cluster labels are written back onto interface rows in the merged `pdb.parquet`.

Because the chunked examples now use `superimpose_to_reference`, they are the most natural place to use coordinate-based dataset clustering on aligned prepared structures.

## Profiles

- antibody-antigen: heavy/light antibody binder against antigen
- VHH-antigen: single-chain binder against antigen
- protein-protein: generic non-antibody interface analysis

## Notes

- `dataset_analysis_mode: post_merge` is the cleanest default for clustering because clusters are only meaningful on the merged dataset.
- If you need per-chunk analyses for operational reasons, keep `cluster` commented out unless you explicitly want per-chunk cluster labels.
