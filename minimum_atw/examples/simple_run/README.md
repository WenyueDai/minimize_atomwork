# Simple Run Examples

For **small datasets (< 10 structures)** with complete analysis including Rosetta InterfaceAnalyzer metrics.

## Quick Start

**Light mode (fast, ~2-3 min per structure):**
```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
```

**Full mode (complete analysis, ~5-10 min per structure):**
```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

## Config Files

| File | Use For |
|------|---------|
| `example_antibody_antigen_light.yaml` | Fast testing: minimal plugins, still includes Rosetta |
| `example_antibody_antigen_pdb.yaml` | Complete analysis: all plugins, CDR entropy, etc. |
| `example_vhh_antigen.yaml` | Nanobody/VHH systems |
| `example_protein_protein_complex.yaml` | Generic protein-protein (no antibody features) |

## Rosetta Setup

All examples require Rosetta InterfaceAnalyzer. Set paths once:

```bash
export ROSETTA_INTERFACE_ANALYZER="/path/to/InterfaceAnalyzer.static.linuxgccrelease"
export ROSETTA_DATABASE="/path/to/rosetta/database"
```

Or edit each config's `rosetta_executable` and `rosetta_database` fields.

**Verify:**
```bash
which InterfaceAnalyzer.static.linuxgccrelease && echo $ROSETTA_DATABASE
```

## Rosetta Packing Options

Customize packing behavior in YAML (all optional, defaults shown):

```yaml
# Packing configuration
rosetta_pack_input: true              # Repack sidechains at interface
rosetta_pack_separated: true          # Separate chains during repacking
rosetta_compute_packstat: true        # Calculate packing quality scores
rosetta_atomic_burial_cutoff: 0.01    # Buried polar atom threshold
rosetta_interface_cutoff: 8.0         # Interface distance (Å)
```

### Common Packing Modes

**Input sidechains only (no repacking, fastest):**
```yaml
rosetta_pack_input: false
rosetta_compute_packstat: false
```

**Packed sidechains with metrics (default, recommended):**
```yaml
rosetta_pack_input: true
rosetta_pack_separated: true
rosetta_compute_packstat: true
```

**Quick testing mode:**
```yaml
rosetta_pack_input: true
rosetta_compute_packstat: true
rosetta_atomic_burial_cutoff: 0.1     # Less stringent
```

## Output

All configs produce:
- `summary.parquet` — one row per structure
- `interfaces.parquet` — one row per interface pair
  - Rosetta metrics: `iface__rosetta_dg_separated`, `iface__rosetta_packstat`, `iface__rosetta_dsasa`
- `dataset_summary.parquet` — aggregated statistics

Antibody configs also add CDR interface columns when numbering is enabled.

## Advanced: Run Individual Plugins

```bash
CONFIG=example_antibody_antigen_pdb.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli prepare --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_contacts
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin rosetta_interface_example
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli analyze-dataset --config "$CONFIG"
```
