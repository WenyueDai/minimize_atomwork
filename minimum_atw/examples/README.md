# Examples

Example configs for `minimum_atw`. Each YAML is intended to be both runnable and readable as a template.

Python environment:
`/home/eva/miniconda3/envs/atw_pp/bin/python`

Working directory:
`/home/eva/minimum_atomworks`

## Quick start

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
```

Stage-by-stage:

```bash
CONFIG=/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli prepare --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-plugin --config "$CONFIG" --plugin interface_metrics
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge --config "$CONFIG"
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli analyze-dataset --config "$CONFIG"
```

## Example folders

- [simple_run/](simple_run/README.md): one-shot local runs and plugin development
- [large_run/](large_run/README.md): `run-chunked`, `plan-chunks`, and `merge-planned-chunks`
- [chunk_run/](chunk_run/README.md): manual one-config-per-chunk workflows
- [multi_dataset/](multi_dataset/README.md): compare clustering within each dataset, then on pooled merged outputs

## Config keys and when to use them

### Core paths and naming

| Key | Meaning | Turn on / set it when | Leave default / commented when |
|---|---|---|---|
| `input_dir` | Directory containing `.pdb` / `.cif` inputs | Always | Never |
| `out_dir` | Output directory for this run | Always | Never |
| `assembly_id` | Assembly label recorded on output rows | Your source structures need a non-default assembly tag | `"1"` is fine |
| `pdb_output_name` | Final merged per-structure table filename | You need distinct output filenames in the same out dir | `pdb.parquet` is fine |
| `dataset_output_name` | Final dataset-analysis filename | You need distinct output filenames | `dataset.parquet` is fine |

### Interface definition

| Key | Meaning | Turn on / set it when | Leave default / commented when |
|---|---|---|---|
| `roles` | Named chain groups used throughout the pipeline | Always | Never |
| `interface_pairs` | Which role-role interfaces to compute | Always for interface work | No interface plugins are enabled |

### Prepare phase

| Key | Meaning | Turn on / set it when | Leave default / commented when |
|---|---|---|---|
| `manipulations` | Runnable prepare-plugin list. Each item is `{name, grain}` and includes both QC plugins like `chain_continuity` / `structure_clashes` and structural transforms like `center_on_origin` | You want any prepare-phase QC or coordinate edits | You want untouched inputs and no QC annotations |
| `quality_controls` | Readability-only grouping label shown as comments in some YAMLs | You are scanning example templates and want to see which entries are QC vs structure transforms | You are writing the active runnable config; put the real entries in `manipulations` |
| `clash_distance` | Distance threshold used by `structure_clashes` | You want a stricter or looser clash definition | `2.0` works |
| `clash_scope` | Clash scope for `structure_clashes` | You only care about inter-chain or interface clashes | `all` works |

### Per-structure calculations

| Key | Meaning | Turn on / set it when | Leave default / commented when |
|---|---|---|---|
| `plugins` | Per-structure calculations merged into `pdb.parquet` | Always for execute phase | Never |
| `contact_distance` | Contact cutoff used by interface plugins | You want to tune interface strictness | `5.0` works |
| `interface_cell_size` | Grid size override for interface metrics | You are tuning interface-metrics performance / behavior | Let it derive from `contact_distance` |
| `abepitope_atom_radius` | Radius passed to AbEpiTope interface detection | You need a non-default AbEpiTope interface radius | `abepitope_score` is off |

### Plugin-specific configuration

| Key | Meaning | Turn on / set it when | Leave default / commented when |
|---|---|---|---|
| `plugin_params` | Per-plugin nested config dict | A plugin has settings that should not be global | The plugin has no extra settings |
| `superimpose_reference_path` | Global fallback reference path for the active superposition path | You want all structures aligned to one reference complex or even a single reference chain | You set the per-plugin `reference_path` explicitly |
| `superimpose_on_chains` | Global fallback anchor chains for superposition | You want to align on only part of the complex, such as antigen chain `A` while still transforming the full antibody-antigen complex | You set the per-plugin `on_chains` explicitly |

### Antibody-specific controls

| Key | Meaning | Turn on / set it when | Leave default / commented when |
|---|---|---|---|
| `numbering_roles` | Which roles should be treated as antibody chains | You use CDR or antibody-specific plugins | Non-antibody datasets |
| `numbering_scheme` | Antibody numbering scheme | You need a specific numbering convention | `imgt` works |
| `cdr_definition` | CDR boundary convention | You need North or Kabat boundaries, or use `aho` numbering | `imgt` works |

### Dataset analyses

| Key | Meaning | Turn on / set it when | Leave default / commented when |
|---|---|---|---|
| `dataset_analyses` | Post-merge or per-chunk analyses | You want `dataset.parquet` or dataset write-backs | You only need `pdb.parquet` |
| `dataset_analysis_mode` | When dataset analyses run | `per_chunk` for manual chunk outputs, `post_merge` for biologically meaningful merged analyses, `both` for both | `post_merge` is usually the clean default |
| `dataset_analysis_params` | Nested parameters per dataset analysis | You need plugin-specific dataset-analysis options | Defaults are fine |
| `cleanup_prepared_after_dataset_analysis` | Delete the whole `_prepared/` directory after dataset analysis completes successfully | You want to save disk after a finalized analysis run and do not plan to rerun dataset analyses from aligned prepared structures | You want to keep re-analysis possible or `_prepared/` is already absent |
| `dataset_annotations` | Literal annotations copied into dataset outputs. Only `dataset_id` and `dataset_name` are also stamped onto every `pdb.parquet` row as `dataset__id` and `dataset__name` | You want provenance, labels, project metadata, or stable dataset identity during `merge-datasets` | You do not care about dataset metadata |
| `reference_dataset_dir` | External dataset outputs used by certain analyses | You are comparing against a baseline dataset | No reference comparison is needed |

### Runtime and resume

| Key | Meaning | Turn on / set it when | Leave default / commented when |
|---|---|---|---|
| `keep_intermediate_outputs` | Keep `_prepared` and `_plugins` outputs instead of staging into temp dirs | You are debugging, iterating on one plugin, or want reusable intermediates | Normal production one-shot runs |
| `keep_prepared_structures` | Save prepared structures to disk | You want to inspect or reuse prepared coordinates, or you use `superimpose_to_reference` and want later dataset analyses to reload aligned structures | You only need merged tabular outputs and are not using prepare-stage superposition |
| `checkpoint_enabled` | Resume prepare / plugin execution from previous outputs | Long runs, unstable environments, scheduler preemption | Short local runs |
| `checkpoint_interval` | Intended checkpoint cadence metadata | You are documenting your chosen resume cadence | You are not using checkpointing |

### Rosetta-only controls

These only matter if `rosetta_interface_example` is enabled.

| Key | Meaning | Turn on / set it when | Leave default / commented when |
|---|---|---|---|
| `rosetta_executable` | InterfaceAnalyzer binary | Rosetta is enabled | Rosetta is off |
| `rosetta_database` | Rosetta database path | Rosetta is enabled | Rosetta is off |
| `rosetta_score_jd2_executable` | `score_jd2` binary for optional preprocessing | You want Rosetta preprocessing | Rosetta preprocessing is off |
| `rosetta_preprocess_with_score_jd2` | Preprocess input before InterfaceAnalyzer | Your Rosetta inputs need cleanup | Rosetta is off |
| `rosetta_interface_targets` | Explicit Rosetta target definitions | You need role- or chain-specific Rosetta targets | `interface_pairs` are enough |
| `rosetta_pack_input` etc. | Rosetta scoring / packing toggles | You are tuning Rosetta behavior | Rosetta is off |

## Built-in plugin inventory

### Prepare plugins

| Name | YAML key | What it does |
|---|---|---|
| `chain_continuity` | `manipulations` | Flags residue-ID gaps and likely chain breaks |
| `structure_clashes` | `manipulations` | Counts atom clashes |
| `center_on_origin` | `manipulations` | Recenters the structure coordinates |
| `superimpose_to_reference` | `manipulations` | Aligns the full structure during prepare and rewrites `ctx.aa` to the transformed coordinates |

### Per-structure plugins

| Name | What it produces |
|---|---|
| `identity` | Structure / chain / role identity rows |
| `chain_stats` | Per-chain sequence and size stats |
| `role_sequences` | Per-role sequences |
| `role_stats` | Per-role atom and residue counts |
| `interface_contacts` | Interface contact and residue annotations |
| `interface_metrics` | Interface residue-pair summary metrics |
| `antibody_cdr_lengths` | CDR lengths for antibody roles |
| `antibody_cdr_sequences` | CDR sequences for antibody roles |
| `abepitope_score` | AbEpiTope scores for antibody-antigen interfaces |
| `superimpose_homology` | Legacy metrics-only superposition plugin; prefer `superimpose_to_reference` when downstream analyses should use aligned coordinates |
| `rosetta_interface_example` | Example Rosetta InterfaceAnalyzer integration |

### Dataset analyses

| Name | What it produces |
|---|---|
| `dataset_annotations` | Dataset-level metadata rows |
| `interface_summary` | Aggregated interface summaries |
| `cluster` | Cluster labels written back onto interface rows |
| `cdr_entropy` | Sequence entropy for configured CDR roles / regions |

## Outputs

| File | Meaning |
|---|---|
| `pdb.parquet` | All `structure`, `chain`, `role`, and `interface` rows |
| `dataset.parquet` | Dataset-analysis rows |
| `run_metadata.json` | Run config, counts, and output-file metadata |
| `dataset_metadata.json` | Merged dataset metadata |
| `_prepared/` and `_plugins/` | Intermediate outputs kept when `keep_intermediate_outputs: true` |

## Output Column Reference

### `pdb.parquet`: common identity columns

These columns exist to identify the row. Most are blank on grains where they do not apply.

| Column | Meaning |
|---|---|
| `path` | Original source structure path |
| `assembly_id` | Assembly label from config |
| `grain` | Row type: `structure`, `chain`, `role`, or `interface` |
| `dataset__id` | Stable dataset identifier copied onto every row; default order is `dataset_annotations.dataset_id`, then `dataset_annotations.dataset_name`, then `out_dir` name |
| `dataset__name` | Human-readable dataset label copied onto every row; defaults to `dataset_annotations.dataset_name`, else `dataset__id` |
| `chain_id` | Chain identifier for `grain == "chain"` |
| `role` | Role name for `grain == "role"` |
| `pair` | Interface label such as `antibody__antigen` |
| `role_left` | Left role for interface rows |
| `role_right` | Right role for interface rows |
| `sub_id` | Reserved extension identity column; usually blank in built-in outputs |

### `pdb.parquet`: `grain == "structure"`

| Column or pattern | Meaning |
|---|---|
| `source__name` | Input filename |
| `source__format` | Input file format such as `pdb` or `cif` |
| `source__size_bytes` | Source file size |
| `source__n_atoms_loaded` | Number of atoms loaded from the source structure |
| `source__n_chains_loaded` | Number of chains loaded from the source structure |
| `prepared__path` | Absolute path to the saved prepared structure. This is always preserved when `superimpose_to_reference` is enabled, because later dataset analyses may need to reload the aligned structure |
| `id__n_atoms_total` | Total atom count in the loaded structure |
| `id__n_chains` | Total number of chain IDs seen in the structure |
| `id__has_nan_coord` | Whether any atom coordinate is `NaN` |
| `center__centroid_x`, `center__centroid_y`, `center__centroid_z` | Original centroid before `center_on_origin` shifts the structure |
| `clash__has_clash` | Whether any clashes were detected |
| `clash__n_clashing_atom_pairs` | Number of atom-atom clash pairs |
| `clash__n_clashing_atoms` | Number of unique atoms participating in clashes |
| `sup__reference_path` | Reference structure path used by the active superposition path. This can come from the prepare-stage `superimpose_to_reference` manipulation or from the `superimpose_homology` plugin |
| `sup__on_chains` | Semicolon-separated chain IDs used as the alignment anchor. These chains decide which atoms drive the fit; they do not by themselves decide which atoms contribute to RMSD |
| `sup__anchor_atoms_fixed`, `sup__anchor_atoms_mobile` | Number of matched atoms from the reference (`fixed`) and the moving structure (`mobile`) that were actually used to compute the alignment transform. If this count is unexpectedly small, the fit is probably fragile |
| `sup__alignment_method` | Alignment routine used. `superimpose_homology` reports `homologs` or `structural_homologs`; prepare-stage superposition uses the same underlying matching logic |
| `sup__shared_atoms_rmsd` | RMSD after the transform is applied, computed on all atoms that are shared between the reference structure and the transformed mobile structure. This is broader than the anchor set: for example, you can fit on chain `A` and still measure RMSD on shared atoms from `A`, `B`, and `C` if the reference contains all three |
| `sup__shared_atoms_count` | Number of shared atoms contributing to `sup__shared_atoms_rmsd` |
| `sup__coordinates_applied` | Present only for the prepare-stage `superimpose_to_reference` manipulation. `true` means the saved prepared coordinates were actually rewritten into the aligned frame |
| `sup__note` | Present only when no explicit reference path was provided and the first structure became the implicit reference |
| `sup__transformed_path` | Absolute path to a persisted transformed structure written only by `superimpose_homology` when `plugin_params.superimpose_homology.persist_transformed_structures: true` |

### `pdb.parquet`: `grain == "chain"`

| Column or pattern | Meaning |
|---|---|
| `id__n_atoms` | Atom count for the chain |
| `continuity__has_break` | Whether the chain appears discontinuous |
| `continuity__n_breaks` | Estimated number of breaks; `-1` means QC failed and the chain was marked broken |
| `chstat__n_residues` | Unique residue count in the chain |
| `chstat__centroid_x`, `chstat__centroid_y`, `chstat__centroid_z` | Chain centroid coordinates |
| `chstat__radius_of_gyration` | True radius of gyration for the chain |
| `sup__rmsd` | Chain-level RMSD after superposition, for chains shared with the reference |
| `sup__matched_atoms` | Number of matched atoms used in `sup__rmsd` |

### `pdb.parquet`: `grain == "role"`

| Column or pattern | Meaning |
|---|---|
| `id__n_atoms` | Atom count for the role selection |
| `rolseq__chain_ids` | Semicolon-separated chain IDs assigned to the role |
| `rolseq__n_chains` | Number of chains in the role |
| `rolseq__sequence_length_total` | Sum of sequence lengths across all chains in the role |
| `rolseq__sequence` | Concatenated sequence when the role contains a single chain; blank for multi-chain roles |
| `rolseq__sequence_by_chain` | JSON mapping of chain ID to sequence |
| `rolstat__n_residues` | Unique residue count for the role |
| `rolstat__centroid_x`, `rolstat__centroid_y`, `rolstat__centroid_z` | Role centroid coordinates |
| `rolstat__radius_of_gyration` | True radius of gyration for the role selection |
| `abcdr__chain_ids` | Chain IDs used for antibody CDR-length analysis |
| `abcdr__numbering_scheme` | Antibody numbering scheme such as `imgt` |
| `abcdr__cdr_definition` | CDR boundary definition used |
| `abcdr__sequence_length` | Full antibody sequence length used for numbering |
| `abcdr__cdr1_length`, `abcdr__cdr2_length`, `abcdr__cdr3_length` | CDR lengths |
| `abseq__chain_ids` | Chain IDs used for antibody CDR-sequence analysis |
| `abseq__numbering_scheme` | Antibody numbering scheme |
| `abseq__cdr_definition` | CDR boundary definition used |
| `abseq__sequence_length` | Full antibody sequence length used for numbering |
| `abseq__cdr1_sequence`, `abseq__cdr2_sequence`, `abseq__cdr3_sequence` | CDR amino-acid sequences |

### `pdb.parquet`: `grain == "interface"`

| Column or pattern | Meaning |
|---|---|
| `iface__contact_distance` | Atom-atom contact cutoff used to define the interface |
| `iface__n_contact_atom_pairs` | Raw atom-level contact count at the configured cutoff. Every left-side atom within `iface__contact_distance` of a right-side atom contributes one pair, so this number grows with both interface size and local packing density |
| `iface__n_left_contact_atoms`, `iface__n_right_contact_atoms` | Number of contact atoms on each interface side |
| `iface__n_left_interface_residues`, `iface__n_right_interface_residues` | Number of interface residues on each side |
| `iface__left_interface_residues`, `iface__right_interface_residues` | Semicolon-separated residue tokens `chain:res_id:res_name` |
| `iface__n_<side>_<role>_cdr<1/2/3>_interface_residues` | Dynamic antibody-interface count columns from `interface_contacts`; names depend on side (`left` or `right`) and role name such as `vh`, `vl`, or `vhh` |
| `iface__<side>_<role>_cdr<1/2/3>_interface_residues` | Dynamic residue-token lists for the matching CDR interface residues |
| `ifm__contact_distance` | Contact cutoff recorded by `interface_metrics`; may be pruned if identical to `iface__contact_distance` |
| `ifm__cell_size` | Cell-list bin size used by `interface_metrics`; may be pruned if redundant |
| `ifm__n_residue_contact_pairs` | Number of unique contacting residue pairs |
| `ifm__residue_contact_pairs` | Semicolon-separated residue-residue contact tokens `left_chain:left_res:left_name|right_chain:right_res:right_name`. This collapses many atom-atom contacts into unique residue pairs, which is usually easier to compare across structures than `iface__n_contact_atom_pairs` |
| `ifm__left_interface_residue_labels`, `ifm__right_interface_residue_labels` | Semicolon-separated residue labels `chain:res_id` for interface residues on each side |
| `ifm__left_n_interface_residues`, `ifm__right_n_interface_residues` | Interface-residue counts on each side; may duplicate `iface__...` columns |
| `ifm__left_interface_charge_sum`, `ifm__right_interface_charge_sum` | Net charge sum over interface residues on each side |
| `ifm__left_interface_hydrophobic_fraction`, `ifm__right_interface_hydrophobic_fraction` | Fraction of interface residues that are hydrophobic |
| `ifm__left_interface_polar_fraction`, `ifm__right_interface_polar_fraction` | Fraction of interface residues that are polar |
| `ifm__left_interface_aromatic_fraction`, `ifm__right_interface_aromatic_fraction` | Fraction of interface residues that are aromatic |
| `ifm__left_interface_glycine_fraction`, `ifm__right_interface_glycine_fraction` | Fraction of interface residues that are glycine |
| `ifm__left_interface_proline_fraction`, `ifm__right_interface_proline_fraction` | Fraction of interface residues that are proline |
| `abepitope__atom_radius` | Radius used when AbEpiTope defines the antibody-antigen neighborhood |
| `abepitope__score`, `abepitope__target_score` | Common AbEpiTope scores returned by the backend |
| `abepitope__*` | Additional backend-specific AbEpiTope metrics if present |
| `rosetta__database_path` | Rosetta database path used for InterfaceAnalyzer |
| `rosetta__interface_dg`, `rosetta__interface_dg_separated`, `rosetta__interface_dsasa`, `rosetta__interface_packstat`, `rosetta__interface_sc_value`, ... | Rosetta InterfaceAnalyzer metrics when `rosetta_interface_example` is enabled |
| `cluster__<job_name>_cluster_id` | Arbitrary cluster label written by the dataset-level `cluster` analysis back onto interface rows. The numeric value is only meaningful within that one clustering job; `cluster_id = 3` in one job has no relationship to `cluster_id = 3` in another |
| `cluster__<job_name>_cluster_size` | Number of interface rows assigned to the same cluster. Large values indicate a recurrent interface shape under that job's settings |
| `cluster__<job_name>_representative_path` | Path of the medoid-like representative structure chosen for the cluster. This is the concrete example closest to the rest of the cluster under the job distance metric |
| `cluster__<job_name>_distance_to_representative` | Distance from this interface to the representative interface. Lower means more central; higher means more peripheral or unusual within the cluster |
| `cluster__<job_name>_n_points` | Number of CA points used to build the point cloud for this interface. This depends on the selected interface side, the residues present there, and the clustering mode |
| `cluster__<job_name>_interface_side` | Which interface side was clustered by this job, usually `left` or `right`. In antibody-antigen work this is often paratope vs epitope depending on how you assigned `role_left` and `role_right` |
| `cluster__<job_name>_mode` | How the point cloud was built before clustering. `interface_ca` uses the canonical structure for that row, which means aligned prepared structures when `prepared__path` exists. `superimposed_interface_ca` is a legacy explicit mode for plugin-persisted transformed structures |

### `dataset.parquet`

Rows from multiple dataset analyses are concatenated into one table, so some columns are only populated for certain `analysis` values.

| Column or pattern | Meaning |
|---|---|
| `analysis` | Dataset analysis name that produced the row |
| `key`, `value`, `source` | `dataset_annotations` rows: metadata key/value pairs, with `source` as `derived` or `config` |
| `pair` | Interface pair summarized by `interface_summary` |
| `n_rows` | Number of interface rows contributing to that summary |
| `n_unique_paths` | Number of unique structures in that summary |
| `mean_contact_atom_pairs` | Mean of `iface__n_contact_atom_pairs` over the summarized rows |
| `mean_left_interface_residues`, `mean_right_interface_residues` | Mean interface-residue counts on each side |
| `role` | Role name for `cdr_entropy` rows |
| `region` | Region summarized by `cdr_entropy`: `cdr1`, `cdr2`, `cdr3`, or `sequence` |
| `cdr` | Same as `region` for CDR regions, blank for full-sequence rows |
| `source_column` | Input role-column used to compute the entropy |
| `n_sequences` | Number of sequences contributing to the entropy estimate |
| `n_unique_sequences` | Number of unique sequences in that set |
| `shannon_entropy` | Shannon entropy over the selected sequences |

Built-in `cluster` currently writes its results back onto `pdb.parquet` interface rows and does not add rows to `dataset.parquet`.

## Notes

- `cluster` writes labels back onto `grain == "interface"` rows in `pdb.parquet`, not only into `dataset.parquet`.
- Set `dataset_annotations.dataset_id` for every run if you plan to compare or merge datasets. `dataset_id` and `dataset_name` are copied into `pdb.parquet` as `dataset__id` and `dataset__name` on every row and preserved by `merge-datasets`.
- For chunked workflows, `dataset_analysis_mode: post_merge` is usually the right default for clustering and other whole-dataset summaries.
- For cross-dataset comparison, the current built-in pattern is "run each dataset separately, merge out_dirs, then analyze the merged output". `reference_dataset_dir` is wired into the runtime but not yet used by the built-in analyses.
- If you want downstream calculations to use aligned coordinates, use `superimpose_to_reference` in `manipulations`. That is the canonical superposition path for normal runs.
- The alignment anchor and the RMSD atom set are different concepts. `on_chains` controls which atoms drive the fit. `sup__shared_atoms_rmsd` is then computed over the atoms shared between the reference file and the transformed mobile structure. If the reference file contains only chain `A`, the RMSD is effectively on `A`. If the reference file contains `A-B-C` but `on_chains: ["A"]`, the fit is anchored on `A` while the RMSD can still include shared atoms from `A`, `B`, and `C`.
- `superimpose_to_reference` is a prepare-stage manipulation. It rewrites the structure coordinates, and the config automatically preserves the prepared aligned structures so later dataset analyses can reload them.
- `superimpose_homology` is a legacy metrics-only plugin. It can still report alignment metrics or persist transformed files, but it is not the recommended path when downstream calculations should run on aligned coordinates.
- Do not enable `superimpose_to_reference` and `superimpose_homology` in the same run. Both write `sup__*` columns, so the config now requires you to choose either prepare-stage coordinate rewriting or plugin-stage superposition metrics.
- If `prepared__path` exists, `cluster.mode: interface_ca` already reloads the prepared structure for each row. So when you use `superimpose_to_reference`, normal clustering already uses aligned coordinates.
- `cluster.mode: superimposed_interface_ca` is mostly for the legacy plugin-style superposition path. It prefers `sup__transformed_path` from persisted `superimpose_homology` outputs and otherwise falls back to aligned prepared structures.
- `cleanup_prepared_after_dataset_analysis: true` removes the whole `_prepared/` directory only after dataset analysis succeeds. Use it to save disk at the cost of making later re-analysis from aligned prepared structures impossible.
- The YAMLs intentionally keep many optional flags commented out so each example can double as a starting template.
