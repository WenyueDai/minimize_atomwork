# Examples

This directory contains runnable example configs for `minimum_atomworks` on this machine.

**All examples now include Rosetta InterfaceAnalyzer** for high-quality binding metrics. Configure Rosetta via environment variables or YAML before running.

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

- you have **< 10 structures** (Rosetta will run serially)
- you want the easiest starting point
- you are testing plugins or configurations
- you have sufficient time for serial processing (5-30 min per structure)

Use [chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md) if:

- you want manual control over chunks
- you want one scheduler job per chunk (manual orchestration)
- you want explicit debugging of each chunk run

Use [large_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md) if:

- you have **50+ structures** and want efficient resource usage
- you want automatic chunking with `run-chunked` (one job with internal workers)
- OR you want `plan-chunks` (generate chunk configs for Slurm arrays)
- **Rosetta will run in parallel across workers/jobs** (critical for large datasets)

## Best commands to try first

### Quick test (1-5 structures, ~2-3 min with Rosetta)

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
```

### Full analysis (1-5 structures, ~5-10 min with Rosetta)

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

### Large dataset with internal parallelism (50+ structures, efficient resource use)

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --workers 4
```

Expected: ~100 structures with 4 workers = ~5-10 hours (Rosetta runs in parallel, CPU-bound)

### Large dataset with Slurm array (scheduler manages chunks)

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli plan-chunks \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --plan-dir /home/eva/minimum_atomworks/out_antibody_antigen_chunk_plan
```

Then submit array jobs (see `large_run/README.md` for Slurm examples)

## Ready-to-run configs

Simple runs (all include Rosetta):

- `/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml` (full analysis)
- `/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml` (minimal, fast)
- `/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml` (VHH/nanobody)
- `/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml` (generic protein-protein)

Manual chunk runs:

- `/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml`
- `/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml`

Automatic chunked run:

- `/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml` (includes Rosetta)

## Rosetta Configuration

Before running any examples, set up Rosetta paths:

```bash
export ROSETTA_INTERFACE_ANALYZER="/path/to/InterfaceAnalyzer.static.linuxgccrelease"
export ROSETTA_DATABASE="/path/to/rosetta/database"
```

Or edit the YAML configs directly with your paths.

**Check your installation:**
```bash
which InterfaceAnalyzer.static.linuxgccrelease && echo $ROSETTA_DATABASE
```

If Rosetta is not available, the plugins will skip gracefully but interface metrics will be missing.

## Notes

- **Rosetta Requirement**: All examples now include Rosetta InterfaceAnalyzer for high-quality binding metrics. Configure via environment variables or YAML.
- **Data Paths**: These are concrete working examples; always verify `input_dir`, `out_dir`, and Rosetta executable paths before reusing elsewhere.
- **Rosetta Performance Impact**: Rosetta is computationally expensive (5-30s per interface pair). For many structures, use chunking (`large_run/`) to parallelize.
- **Resource Strategy**:
  - **< 10 structures**: Use `simple_run/` (serial execution acceptable)
  - **10-100 structures**: Use `large_run/` with `run-chunked` and 2-4 workers
  - **100+ structures**: Use `large_run/` with `plan-chunks` and Slurm arrays
- **Light vs Full**: All examples show both fast (light) and comprehensive (full) variants for iteration vs. production use.
- **Antibody Numbering**: Examples show active numbering config with alternatives commented out.
- **CDR Entropy**: Multi-region variants shown in comments.
