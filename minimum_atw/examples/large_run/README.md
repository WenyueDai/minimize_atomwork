# Large Run Example

This folder is for `run-chunked` and `plan-chunks`.

The shipped config follows the same local-development rule as the small examples:

- all non-Rosetta features are enabled
- the full Rosetta block is present but commented out

## Config

- [example_antibody_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml)

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

- both built-in manipulations
- all non-Rosetta antibody/interface plugins
- dataset analyses including `cdr_entropy`
- cache/checkpoint toggles as commented options
- the full Rosetta config block ready for later activation

## Enabling Rosetta later

Uncomment the Rosetta plugin and Rosetta config block in [example_antibody_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml). The scaffold already includes the current Rosetta controls used by this package.
