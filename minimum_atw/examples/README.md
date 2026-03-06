# Examples

This directory contains runnable example configs for `minimum_atomworks` on this machine.

Use this Python environment for all commands below:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python
```

Run commands from:

```bash
cd /home/eva/minimum_atomworks
```

## Which example should you use?

Use [simple_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/README.md) if:

- you want one dataset in one output directory
- you want the easiest starting point
- you are testing plugins or schema changes

Use [chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md) if:

- you want manual chunk configs
- you want one scheduler job per chunk
- you want explicit control over each chunk run

Use [large_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md) if:

- you want `run-chunked`
- you want one larger job with internal parallel workers
- or you want `plan-chunks` to generate scheduler-ready chunk configs automatically

## Best commands to try first

1. Full antibody-antigen run

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

2. Faster light run

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
```

3. Automatic chunked run

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 5 \
  --workers 2
```

4. Planned chunk workflow for Slurm arrays

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli plan-chunks \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 5 \
  --plan-dir /home/eva/minimum_atomworks/out_antibody_antigen_chunk_plan
```

5. Manual chunk run

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml
```

## Ready-to-run configs

Simple runs:

- `/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml`
- `/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml`
- `/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml`
- `/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml`

Manual chunk runs:

- `/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml`
- `/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml`

Automatic chunked run:

- `/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml`

## Notes

- The example YAMLs are meant to be runnable here, but you should still inspect `input_dir`, `out_dir`, and optional external-tool paths before reusing them elsewhere.
- Antibody and VHH examples can write CDR-specific interface columns in `interfaces.parquet` when `numbering_roles` and `interface_contacts` are enabled.
- The example YAMLs intentionally show many optional built-in features as comments so the available extension surface is visible in one place.
