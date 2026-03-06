# Simple Run Examples

This folder is for one dataset -> one output directory.

Use these examples if:

- you want the easiest way to run `minimum_atomworks`
- you want to inspect one finished dataset
- you are testing plugin behavior or schema changes
- you have a **small number of structures** (< 10-50 depending on resources)

## Files

All examples include Rosetta InterfaceAnalyzer for high-quality binding metrics.

**Standard configs** (include all analysis):
- `example_antibody_antigen_pdb.yaml` — full antibody analysis + Rosetta
- `example_vhh_antigen.yaml` — VHH/nanobody analysis + Rosetta
- `example_protein_protein_complex.yaml` — generic protein-protein + Rosetta

**Light configs** (faster, skips some plugins):
- `example_antibody_antigen_light.yaml` — minimal plugins + Rosetta
- `example_antibody_antigen_light_with_rosetta.yaml` — identical to light config

**Rosetta-enabled variants** (included for reference, equivalent to standard):
- `example_antibody_antigen_pdb_with_rosetta.yaml`
- `example_vhh_antigen_with_rosetta.yaml`
- `example_protein_protein_complex_with_rosetta.yaml`

## What these examples show

The YAML files expose the built-in feature surface directly in comments including:

- manipulations: `center_on_origin`, `superimpose_homology`
- record plugins: `identity`, `chain_stats`, `role_sequences`, `role_stats`, `interface_contacts`, `antibody_cdr_lengths`, `antibody_cdr_sequences`, `rosetta_interface_example`
- dataset analyses: `dataset_annotations`, `interface_summary`, `cdr_entropy`

**All examples now include `rosetta_interface_example`** for high-quality interface metrics
(`dG_separated`, `packstat`, `dSASA`, etc.). This requires Rosetta to be installed and configured.

## Rosetta Resource Considerations

Rosetta InterfaceAnalyzer is **computationally expensive** compared to pure Python analysis:

| Aspect | Cost |
|--------|------|
| **Per-structure time** | 5-30 seconds per interface pair (depends on protein size) |
| **Memory per process** | 50-200 MB per Rosetta instance |
| **Total runtime** | 1 min (5 structures) → 10 mins (50 structures) → 1+ hour (500 structures) |

### When to Use Simple Runs

✅ **Good for simple runs:**
- Few structures (< 10)
- Quick testing of Rosetta configuration
- Single structures or small datasets
- Interactive development

❌ **Not recommended:**
- 50+ structures (consider chunking instead)
- Parallel job queues (manual coordination needed)
- Long-term batch processing (use chunked runs)

### Memory and CPU Strategy

**Light vs Standard configs:**
- Use `example_*_light.yaml` if memory is constrained (skips heavy Python plugins)
- Use standard configs if you have sufficient resources and want complete analysis

**Rosetta executable choice:**
- `InterfaceAnalyzer.static.linuxgccrelease` — precompiled, no dynamic linking, ~1 min startup overhead
- `InterfaceAnalyzer.default.linuxgccrelease` — dynamically linked, faster startup but needs libraries
- Set via YAML: `rosetta_executable: "..."` or env var: `ROSETTA_INTERFACE_ANALYZER`

## Which config should you start with?

**For quick testing (5-10 structures):**
Use `example_antibody_antigen_light.yaml`:
- Skips superimpose_homology (alignment overhead)
- Minimal Python plugins
- Still includes Rosetta metrics
- ~2 min per structure

**For complete analysis (< 10 structures):**
Use `example_antibody_antigen_pdb.yaml`:
- Full antibody feature extraction
- Complete dataset analysis (CDR entropy, etc.)
- Rosetta metrics for all interfaces
- ~5 min per structure

**For VHH/nanobody systems:**
Use `example_vhh_antigen.yaml` (includes Rosetta)

**For generic protein complexes:**
Use `example_protein_protein_complex.yaml` (includes Rosetta)

**For 50+ structures: DO NOT use simple_run**
→ Use `large_run/` with automatic chunking (see below)

## Fastest command (light variant)

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
```

Expected: ~2-3 min for 1-2 structures with Rosetta

## Full analysis command

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

Expected: ~5-10 min for 1-2 structures with Rosetta

## Rosetta Setup

All examples require Rosetta InterfaceAnalyzer. Configure via:

**Option 1: Set environment variables**
```bash
export ROSETTA_INTERFACE_ANALYZER="/path/to/InterfaceAnalyzer.static.linuxgccrelease"
export ROSETTA_DATABASE="/path/to/rosetta/database"
```

**Option 2: Edit YAML config**
```yaml
rosetta_executable: "/path/to/InterfaceAnalyzer.static.linuxgccrelease"
rosetta_database: "/path/to/rosetta/database"
```

**Option 3: Check installation**
```bash
which InterfaceAnalyzer.static.linuxgccrelease
echo $ROSETTA_DATABASE
```

If Rosetta is not available, the plugin will skip gracefully (no error) but interface metrics will be missing from output.

## Staged Workflow (Advanced)

Use this only if you want to inspect or debug each stage separately:

```bash
CONFIG=/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli prepare --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin identity
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin chain_stats
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_sequences
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_stats
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_contacts
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin rosetta_interface_example  # Rosetta (slowest: 5-30s per interface)
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli analyze-dataset --config "$CONFIG"
```

**Timing notes:**
- Python plugins (identity, chain_stats, etc.): < 1 sec per structure
- **Rosetta step: 5-30 seconds per interface pair** (this is the bottleneck)
- For multiple structures, parallel execution with chunking is recommended (see `large_run/`)

## Important output notes

In antibody and VHH examples, `interface_contacts` can write:

- whole-interface residue columns
  `iface__left_interface_residues`, `iface__right_interface_residues`
- CDR-specific interface columns
  `iface__n_left_vh_cdr1_interface_residues`, `iface__left_vh_cdr1_interface_residues`, `iface__n_left_vl_cdr3_interface_residues`, `iface__left_vl_cdr3_interface_residues`

Residue tokens use:

```text
chain:resi:resn
```

with 1-letter residue codes.

## Other ready-to-run commands

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml
```

## Slurm Examples

### One-shot (all plugins in sequence)

**Light workflow** (1-5 structures):
```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-simple-light
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
EOF
```

**Full workflow** (1-3 structures):
```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-simple-full
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
EOF
```

### Staged (skip Rosetta during testing)

To debug a config without running Rosetta, temporarily remove it from plugins:

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-simple-staged
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

CONFIG=/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml

# Run all plugins EXCEPT Rosetta for quick iteration
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli prepare --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin identity
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin chain_stats
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_sequences
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin role_stats
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_contacts
# Uncomment when ready for Rosetta (will take ~5-30 min per structure)
# /home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin rosetta_interface_example
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli analyze-dataset --config "$CONFIG"
EOF
```

**For large datasets (50+ structures):** Do NOT use simple_run. Instead, use `large_run/` with chunking and parallel workers for better resource utilization.
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli analyze-dataset --config "$CONFIG"
EOF
```

## Important Notes

- **Rosetta Requirement**: All examples now require Rosetta InterfaceAnalyzer. Set `ROSETTA_INTERFACE_ANALYZER` and `ROSETTA_DATABASE` environment variables or edit the YAML configs.
- **Data Paths**: These configs are concrete examples; verify `input_dir`, `out_dir`, and Rosetta paths match your system before running.
- **Rosetta Performance**: Rosetta is the bottleneck (~5-30s per interface pair). For 50+ structures, use `large_run/` with chunking for parallelization.
- **Light vs Full**: Use light configs for quick iteration, full configs for complete analysis.
- **Antibody Numbering**: One active `numbering_scheme` and `cdr_definition` per config; alternatives shown as comments.
- **CDR Entropy**: Multi-region analysis variants shown in comments for reference.
