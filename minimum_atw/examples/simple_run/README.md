# simple_run — local development and plugin testing

Use this folder when you want to run end-to-end on a single dataset and iterate quickly.
All four configs are runnable templates — set `input_dir` and `out_dir` and go.

## Which config?

| Config | Best for |
|---|---|
| [`example_antibody_antigen_light.yaml`](example_antibody_antigen_light.yaml) | **Start here.** Minimal antibody–antigen: identity + interface metrics only |
| [`example_antibody_antigen_pdb.yaml`](example_antibody_antigen_pdb.yaml) | Full antibody–antigen: CDR sequences, AbEpiTope, superimposition |
| [`example_vhh_antigen.yaml`](example_vhh_antigen.yaml) | VHH / nanobody single-domain binder |
| [`example_protein_protein_complex.yaml`](example_protein_protein_complex.yaml) | Generic protein–protein complex |

## Commands

**One-shot run (all stages):**
```bash
python -m minimum_atw.cli run \
  --config minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
```

**Scale the same analysis on Slurm later:**
```bash
python -m minimum_atw.cli submit-slurm \
  --config minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
```

Add a small `slurm:` block with `chunk_size` when you are ready to move from one-node testing to chunked HPC submission. The framework will classify built-in plugins into CPU and GPU stages automatically.

**Iterate on a single plugin without re-running prepare:**
```bash
CONFIG=minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml

# Run prepare once (builds the _prepared/ cache):
python -m minimum_atw.cli prepare --config "$CONFIG"

# Iterate on a specific plugin:
python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_metrics

# Merge and analyze:
python -m minimum_atw.cli merge           --config "$CONFIG"
python -m minimum_atw.cli analyze-dataset --config "$CONFIG"
```

**Inspect available extensions before running:**
```bash
python -m minimum_atw.cli list-extensions
```

## What ends up in `out_dir/`

```
pdb.parquet            ← main output: one row per (structure × grain)
dataset.parquet        ← dataset-level aggregations
run_metadata.json      ← config snapshot + scheduler resource hints
plugin_status.parquet  ← per-plugin structure counts
bad_files.parquet      ← structures that failed to load or QC
```

## Tips

- Turn on `keep_intermediate_outputs: true` to inspect `_prepared/` and `_plugins/` tables.
- GPU-capable plugins (`abepitope_score`, `ablang2_score`, `esm_if1_score`) default to `device: auto`. For local runs you can usually leave the runtime knobs alone. `submit-slurm` will infer whether the job should be CPU-only, mixed, or split by stage from the enabled plugins.
- `cpu_workers`, `gpu_workers`, and `gpu_devices` are optional expert overrides when you want to pin a particular local worker shape.
- `checkpoint_enabled: true` lets you resume a partial run after interruption.

See [`../README.md`](../README.md) for the full config key reference and output column guide.
