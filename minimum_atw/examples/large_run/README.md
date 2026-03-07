# Large Run Example

This folder is for `run-chunked` and `plan-chunks`.

The shipped config follows the same local-development rule as the small examples:

- built-in local features are enabled
- Rosetta blocks are present but commented out
- AbEpiTope is enabled in antibody-oriented chunked examples

## Config

- [example_antibody_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml)
- [example_vhh_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_vhh_antigen_chunked.yaml)
- [example_protein_protein_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_protein_protein_chunked.yaml)

## Profile matrix

- antibody-antigen: paired heavy/light chain binder with antibody-only plugins and CDR entropy
- VHH-antigen: single-chain binder with VHH numbering and CDR entropy
- protein-protein: generic interface analysis without antibody-only plugins

## Run with internal chunk workers

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --workers 2
```

## Plan chunk configs for scheduler use

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli plan-chunks \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --plan-dir /home/eva/minimum_atomworks/out_antibody_antigen_chunk_plan
```

## What the chunked example shows

- both built-in quality controls
- the built-in PDB manipulation
- the built-in dataset manipulation
- the plugin set appropriate for each role model
- dataset analyses, with `cdr_entropy` scaffolded but commented out by default
- `dataset_analysis_mode: post_merge` so chunked runs analyze only the merged final dataset by default
- cache/checkpoint toggles as commented options
- the full Rosetta config block ready for later activation

Merged outputs use the configured parquet names from the YAML. If you do not set them, the defaults remain `pdb.parquet` and `dataset.parquet`.

## Enabling Rosetta later

Uncomment the Rosetta plugin and Rosetta config block in [example_antibody_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml). The scaffold already includes the current Rosetta controls used by this package.
