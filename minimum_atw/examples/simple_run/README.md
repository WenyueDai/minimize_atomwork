# Simple Run Examples

Local runs for development and plugin testing.

```bash
python -m minimum_atw.cli run \
  --config minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
```

## Files

| Config | Profile |
|---|---|
| [example_antibody_antigen_light.yaml](example_antibody_antigen_light.yaml) | Minimal antibody–antigen dev profile |
| [example_antibody_antigen_pdb.yaml](example_antibody_antigen_pdb.yaml) | Full antibody–antigen, all native plugins |
| [example_vhh_antigen.yaml](example_vhh_antigen.yaml) | VHH single-domain binder |
| [example_protein_protein_complex.yaml](example_protein_protein_complex.yaml) | Generic protein–protein complex |

## Staged commands

```bash
CONFIG=minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml

python -m minimum_atw.cli prepare          --config "$CONFIG"
python -m minimum_atw.cli run-plugin       --config "$CONFIG" --plugin interface_contacts
python -m minimum_atw.cli merge            --config "$CONFIG"
python -m minimum_atw.cli analyze-dataset  --config "$CONFIG"
```

## YAML keys at a glance

```yaml
quality_controls:   # run before calculations; annotate without moving atoms
manipulations:      # run before calculations; can transform coordinates
plugins:            # calculations producing rows in pdb.parquet
plugin_params:      # per-plugin config dict (e.g. superimpose_homology params)
dataset_analyses:   # post-merge analyses producing rows in dataset.parquet
```
