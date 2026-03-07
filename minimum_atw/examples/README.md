# Examples

This directory contains runnable example configs for `minimum_atomworks` on this machine.

Current example policy:

- all built-in local features are enabled where they fit the example
- prepare is shown explicitly as quality control -> structure manipulation -> dataset manipulation
- heavy external tools stay scaffolded but commented by default
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

- [example_antibody_antigen_light.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml): local antibody-antigen development with built-in plugins enabled
- [example_antibody_antigen_pdb.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml): full antibody-antigen example
- [example_vhh_antigen.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml): VHH/nanobody-style example
- [example_protein_protein_complex.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml): generic protein-protein example

## Chunked example matrix

`large_run/` now includes one chunk-aware config for each common role model:

- [example_antibody_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml)
- [example_vhh_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_vhh_antigen_chunked.yaml)
- [example_protein_protein_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_protein_protein_chunked.yaml)

`chunk_run/` keeps one canonical manual per-chunk example pair:

- antibody-antigen: [chunk_antibody_antigen_01.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml), [chunk_antibody_antigen_02.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml)

Use `large_run/` when you want chunk-aware variants for VHH-antigen or generic protein-protein profiles.

## Rosetta usage

Each relevant YAML already contains the full Rosetta block:

- plugin entry
- executable/database paths
- optional `score_jd2` preprocessing
- `-fixedchains` target selection
- packing and packstat controls

To enable Rosetta, uncomment the `rosetta_interface_example` plugin and the Rosetta config block in the YAML you want to run.

## AbEpiTope usage

AbEpiTope is available as an optional external plugin:

- plugin name: `abepitope_score`
- output prefix: `abepitope__`
- target table: `interfaces.parquet`

Requirements:

- Python package `abepitope`
- `hmmsearch` from HMMER on `PATH`

The example YAMLs include the plugin as a commented option. Enable it only when those dependencies are installed and the structure is compatible with AbEpiTope's antibody-antigen assumptions.

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

### Prepare-stage sections

- `quality_controls`: prepare-time checks that annotate structures/chains without changing coordinates
- `structure_manipulations`: transforms applied independently to each structure
- `dataset_manipulations`: transforms that depend on a dataset reference or shared dataset context
- `manipulations`: legacy combined prepare list kept for backward compatibility

Built-in prepare units:

- `chain_continuity`: per-chain continuity/gap check
- `structure_clashes`: structure-level steric clash check
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
- `interface_metrics`: interface residue-property and residue-contact-pair metrics
- `abepitope_score`: external AbEpiTope interface scoring for antibody-antigen complexes
- `antibody_cdr_lengths`: antibody/VHH CDR length fields on `roles.parquet`
- `antibody_cdr_sequences`: antibody/VHH CDR sequence fields on `roles.parquet`
- `rosetta_interface_example`: Rosetta InterfaceAnalyzer metrics on `interfaces.parquet`

Use plugin names explicitly. Commenting a plugin out cleanly removes its output columns from the final tables.

Related internal helper modules:

- `minimum_atw.plugins.interface_analysis.interface_metrics`: shared interface-analysis helper code used by both `interface_contacts` and `interface_metrics`; this is not a standalone YAML extension by itself

### Interface analysis settings

- `contact_distance`: atom-atom distance cutoff in Angstroms for `interface_contacts` and `interface_metrics`
- `interface_cell_size`: optional cell-list bin size for `interface_metrics`; when unset, the plugin uses `contact_distance`
- `abepitope_atom_radius`: atom-radius parameter passed to AbEpiTope encoding; only used by `abepitope_score`

These affect the non-Rosetta interface-analysis plugins. Rosetta uses its own `rosetta_*` settings.

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

- `dataset_analyses`: dataset-level analyses such as interface summary or CDR entropy
- `dataset_analysis_mode`: when those analyses run in chunk-aware workflows
  - `post_merge`: run once on the final merged dataset
  - `per_chunk`: run inside each chunk only
  - `both`: run in both places
- `dataset_analysis_params`: per-analysis parameter block

Notes:

- regular `run` always analyzes the dataset in the current `out_dir` after `merge`
- `run-chunked` and `merge-planned-chunks` honor `dataset_analysis_mode`
- low-level `merge-datasets` is merge-only; if you want post-merge dataset analyses there, follow it with `analyze-dataset --config ...`

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
