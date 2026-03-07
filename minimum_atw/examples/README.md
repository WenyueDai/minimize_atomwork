# Examples

This directory contains runnable example configs for `minimum_atomworks` on this machine.

Current example policy:

- all locally testable non-Rosetta features are enabled where they fit the example
- Rosetta InterfaceAnalyzer is fully scaffolded in every relevant YAML
- Rosetta stays commented out by default for local development

Use this Python environment:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python
```

Run commands from:

```bash
cd /home/eva/minimum_atomworks
```

## Which example to start with

Use [simple_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/README.md) for small local runs and plugin development.

Use [chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md) when you want one config per chunk or one scheduler job per chunk.

Use [large_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md) when you want `run-chunked` or `plan-chunks`.

## Ready-to-run local examples

- [example_antibody_antigen_light.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml): local antibody-antigen development, all non-Rosetta features enabled
- [example_antibody_antigen_pdb.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml): full antibody-antigen example
- [example_vhh_antigen.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml): VHH/nanobody-style example
- [example_protein_protein_complex.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml): generic protein-protein example
- [example_antibody_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml): chunked local-development example

## Rosetta usage

Each relevant YAML already contains the full Rosetta block:

- plugin entry
- executable/database paths
- optional `score_jd2` preprocessing
- `-fixedchains` target selection
- packing and packstat controls

To enable Rosetta, uncomment the `rosetta_interface_example` plugin and the Rosetta config block in the YAML you want to run.

## YAML Config Reference

The example YAML files all use the same core config model. The sections below explain what each key means and when you usually need it.

### Required path and structure keys

- `input_dir`: directory containing input `.pdb` or `.cif` files
- `out_dir`: directory where final outputs and temporary working files are written
- `assembly_id`: biological assembly identifier to load from each structure; usually `"1"`

### Role and interface definition

- `roles`: semantic chain groups, written as `{role_name: [chain_ids]}`
  Example: `antibody: ["B", "C"]`
- `interface_pairs`: role pairs that should produce rows in `interfaces.parquet`
  Example: `- ["antibody", "antigen"]`

`roles` define the semantic groups. `interface_pairs` define which of those groups are analyzed as interfaces.

### Prepare-stage manipulations

- `manipulations`: structure transforms applied once during `prepare`

Built-in examples:

- `center_on_origin`: translate coordinates so the structure is centered
- `superimpose_homology`: align to a reference structure using `superimpose_reference_path` and `superimpose_on_chains`

Related keys:

- `superimpose_reference_path`: path to the reference structure used for superposition
- `superimpose_on_chains`: chain IDs used to define the alignment subset

### Record plugins

- `plugins`: per-structure/per-chain/per-role/per-interface calculations to run

Only registered plugins belong in the YAML `plugins:` list. Internal helper modules do not.

Built-in plugins used in the examples:

- `identity`: basic structure-level identity and size fields
- `chain_stats`: one row per chain with chain-level counts
- `role_sequences`: one row per role with sequence strings
- `role_stats`: one row per role with counts and sizes
- `interface_contacts`: interface atom-contact and interface-residue metrics
- `antibody_cdr_lengths`: antibody/VHH CDR length fields on `roles.parquet`
- `antibody_cdr_sequences`: antibody/VHH CDR sequence fields on `roles.parquet`
- `rosetta_interface_example`: Rosetta InterfaceAnalyzer metrics on `interfaces.parquet`

Use plugin names explicitly. Commenting a plugin out cleanly removes its output columns from the final tables.

Related internal helper modules:

- `minimum_atw.plugins.interface_analysis.interface_metrics`: shared interface-analysis helper code used by `interface_contacts`; this is not a standalone plugin and therefore does not belong in YAML

### Interface analysis settings

- `contact_distance`: atom-atom distance cutoff in Angstroms for `interface_contacts`

This only affects the lightweight geometric interface contact plugin, not Rosetta.

### Rosetta settings

These keys only matter when `rosetta_interface_example` is enabled.

- `rosetta_executable`: path to the Rosetta `InterfaceAnalyzer` binary
- `rosetta_database`: path to the Rosetta database directory
- `rosetta_score_jd2_executable`: optional path to `score_jd2`
- `rosetta_preprocess_with_score_jd2`: whether to rewrite problematic input PDBs before InterfaceAnalyzer
- `rosetta_interface_targets`: optional Rosetta-specific interface selections, using role-based or explicit chain-based left/right sides
- `rosetta_pack_input`: run packed mode when `true`, no-pack mode when `false`
- `rosetta_pack_separated`: repack separated partners during Rosetta binding-energy evaluation
- `rosetta_compute_packstat`: request packstat-related Rosetta metrics
- `rosetta_add_regular_scores_to_scorefile`: include standard Rosetta score columns in the scorefile
- `rosetta_packstat_oversample`: optional oversampling factor for more stable packstat values
- `rosetta_atomic_burial_cutoff`: burial threshold used by Rosetta unsatisfied-H-bond style metrics
- `rosetta_sasa_calculator_probe_radius`: probe radius for Rosetta SASA calculations
- `rosetta_interface_cutoff`: interface cutoff passed to Rosetta pose metrics

### Output retention and checkpointing

- `keep_intermediate_outputs`: keep `_prepared/` and `_plugins/` directories after the run
- `keep_prepared_structures`: keep cached prepared structure files instead of discarding them after use
- `checkpoint_enabled`: persist incremental progress so a rerun can resume after failure
- `checkpoint_interval`: flush progress every N structures when checkpointing is on

Use the defaults unless you are debugging, re-running plugins, or dealing with long failure-prone jobs.

### Dataset analyses

- `dataset_analyses`: post-merge analyses that run on the final tables
- `dataset_analysis_params`: per-analysis parameter block

Built-in dataset analyses used in the examples:

- `dataset_annotations`: writes dataset-level metadata into the dataset analysis output
- `interface_summary`: aggregates interface-level metrics across the full dataset
- `cdr_entropy`: computes sequence entropy over chosen antibody/VHH regions

Common `cdr_entropy` parameters:

- `roles`: which role names to include, such as `["vh"]`, `["vl"]`, or `["vh", "vl"]`
- `regions`: which regions to include, such as `["cdr3"]` or `["cdr1", "cdr2", "cdr3", "sequence"]`

### Numbering and CDR extraction

These keys control antibody/VHH-specific plugins and analyses.

- `numbering_roles`: role names that should be treated as numbered antibody-like chains
- `numbering_scheme`: antibody numbering scheme; examples use `imgt`
- `cdr_definition`: CDR definition scheme

These are required for:

- `antibody_cdr_lengths`
- `antibody_cdr_sequences`
- CDR-aware fields emitted by `interface_contacts`
- `cdr_entropy` over antibody/VHH regions

### Dataset metadata

- `dataset_annotations`: free-form metadata copied into dataset-level outputs

Typical uses:

- project or dataset name
- modality such as `antibody_antigen` or `protein_protein`
- chunk ID
- notes about the local profile or data source

### Reading the examples

The example YAMLs follow this pattern:

- active lines show the local-development default
- commented lines show optional alternatives
- Rosetta stays scaffolded but commented until you actually want Rosetta enabled
