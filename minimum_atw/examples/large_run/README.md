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

Because the chunked examples keep `superimpose_homology`, they are the most natural place to use coordinate-based dataset clustering.

## Profiles

- antibody-antigen: heavy/light antibody binder against antigen
- VHH-antigen: single-chain binder against antigen
- protein-protein: generic non-antibody interface analysis

## Notes

- `dataset_analysis_mode: post_merge` is the cleanest default for clustering because clusters are only meaningful on the merged dataset.
- If you need per-chunk analyses for operational reasons, keep `cluster` commented out unless you explicitly want per-chunk cluster labels.
