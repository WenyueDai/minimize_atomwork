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

## Step By Step: What `run` Does

Using [example_antibody_antigen_pdb.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml) as the reference:

1. The CLI loads the YAML into `Config`.
2. Every `.pdb` and `.cif` under `input_dir` is discovered.
3. `prepare` loads each structure and runs the configured manipulations in order:
   - `chain_continuity`
   - `structure_clashes`
   - `center_on_origin`
   - `superimpose_to_reference`
4. Because `superimpose_to_reference` is enabled, the canonical structure coordinates are rewritten before downstream plugins run.
5. The aligned prepared structure is saved under `_prepared/structures`, and `prepared__path` is recorded in `pdb.parquet`.
6. The configured plugins then run on that already-aligned prepared structure:
   - `identity`
   - `chain_stats`
   - `role_sequences`
   - `role_stats`
   - `interface_contacts`
   - `interface_metrics`
   - `antibody_cdr_lengths`
   - `antibody_cdr_sequences`
   - `abepitope_score`
7. `merge` joins the plugin outputs back onto the prepared base rows and writes the final `pdb.parquet`.
8. Because the examples enable dataset analyses, `analyze-dataset` then runs on the merged output and writes `dataset.parquet`.
9. `cluster` writes cluster labels back onto `grain == "interface"` rows in `pdb.parquet`.
10. Since prepare-stage superposition was used, later clustering can reload the aligned prepared structures through `prepared__path`.

### What Persists

- Final outputs stay in your configured `out_dir`.
- The aligned prepared structures stay under `out_dir/_prepared/` by default.
- If you set `cleanup_prepared_after_dataset_analysis: true`, `_prepared/` is deleted only after dataset analysis completes successfully.

## YAML keys at a glance

See [../README.md](/home/eva/minimum_atomworks/minimum_atw/examples/README.md) for the full flag glossary and on/off guidance.

These simple-run YAMLs are the best starting point when:

- you want one config that can run end-to-end locally
- you want to iterate on one plugin with `prepare` + `run-plugin`
- you want to inspect intermediate outputs by turning on `keep_intermediate_outputs`
