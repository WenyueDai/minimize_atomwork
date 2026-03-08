# Simple Run Examples

Local runs for development and plugin testing.
These configs keep the scheduler knobs mostly commented, then write the real planning result to `run_metadata.json` under `plugin_execution.scheduler_resources`.

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

Using [example_antibody_antigen_pdb.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml) as the reference.

`minimum-atw run` calls `run_pipeline(cfg)` which executes four stages in order: **PREPARE → EXECUTE → MERGE → DATASET ANALYSIS**.

### Step 1 — Config and discovery

The CLI validates the YAML into a `Config` object via pydantic. `discover_inputs(cfg.input_dir)` then finds every `.pdb` and `.cif` file recursively. The full list of discovered paths is what drives all subsequent stages.

### Step 2 — PREPARE: QC, manipulation, and cache write

`prepare_outputs(cfg)` iterates over every discovered structure. For each one:

1. Loads the file into a biotite `AtomArray` and builds `Context(aa, chains, roles, config)` with per-chain and per-role slices pre-computed.
2. Runs **quality control** units (`prepare_section='quality_control'`) in config order:
   - `chain_continuity` — checks residue-ID gaps and backbone breaks per chain; writes `continuity__n_breaks`, `continuity__has_break` rows (grain=chain) to the prepare table.
   - `structure_clashes` — counts steric clashes between heavy atoms at `clash_distance` (default 2.0 Å); writes `clash__has_clash`, `clash__n_clashing_atom_pairs`, `clash__n_clashing_atoms` (grain=structure).
3. Runs **structure manipulation** units (`prepare_section='structure'`) in config order:
   - `center_on_origin` — translates `ctx.aa` so its centroid sits at the origin; records `center__centroid_x/y/z` (the pre-translation centroid) and calls `ctx.rebuild_views()` to refresh per-chain and per-role slices.
   - `superimpose_to_reference` — fits `ctx.aa` onto the first structure encountered (or a fixed `reference_path`); mutates `ctx.aa` in place via `ctx.aa = result.fitted_complex`, calls `ctx.rebuild_views()`, then records `sup__shared_atoms_rmsd`, `sup__anchor_atoms`, `sup__alignment_method`, `sup__coordinates_applied=True` (grain=structure) and `sup__rmsd`, `sup__matched_atoms` per shared chain (grain=chain).
4. Saves the transformed `ctx.aa` to `_prepared/structures/<name>.bcif`. The aligned coordinates are what every downstream plugin will see.
5. After all structures, writes:
   - `_prepared/pdb.parquet` — unified table with a `grain` column holding all QC and manipulation output rows.
   - `_prepared/prepared_manifest.parquet` — maps each `source_path` to its `prepared_path`.
   - `_prepared/bad_files.parquet` — structures that failed to load or were flagged fatal by QC.

`_prepared/` is a **cache boundary**. Once it exists and is complete, you can re-run `run-plugin` or `merge` without re-doing QC or superimposition.

### Step 3 — EXECUTE: plugins read from cache, write per-plugin tables

`run_plugins(cfg, plugin_names)` loads `prepared_manifest.parquet`, then for each structure in the manifest:

1. Reads the prepared `.bcif` from `_prepared/structures/`.
2. Rebuilds a fresh `Context(aa, chains, roles, config)` from the cached file — the same aligned coordinates that were saved during prepare.
3. Runs each configured `pdb_calculation` plugin sequentially. The runtime still plans CPU and GPU worker pools here so the finished `run_metadata.json` tells you whether this config is best treated as one mixed job or split CPU/GPU stages on HPC:
   - `identity` — emits identity rows for grain=structure (`id__n_atoms_total`, `id__n_chains`), grain=chain (`id__n_atoms`), and grain=role (`id__n_atoms`) in a single `run()` call.
   - `chain_stats` — emits one grain=chain row per chain: `chstat__n_residues`, `chstat__centroid_x/y/z`, `chstat__radius_of_gyration`.
   - `role_sequences` — emits one grain=role row per role: `rolseq__sequence`, `rolseq__sequence_by_chain`, etc.
   - `role_stats` — emits one grain=role row per role: `rolstat__n_residues`, `rolstat__centroid_x/y/z`, `rolstat__radius_of_gyration`.
   - `interface_contacts` — emits one grain=interface row per role-pair: `iface__n_contact_atom_pairs`, `iface__n_left/right_interface_residues`, `iface__left/right_interface_residues`, plus per-CDR contact columns for antibody roles.
   - `interface_metrics` — emits one grain=interface row per role-pair: `ifm__n_residue_contact_pairs`, `ifm__residue_contact_pairs`, per-side physicochemical fractions.
   - `antibody_cdr_lengths` — emits one grain=role row per antibody role: `abcdr__cdr1/2/3_length`. Calls `available(ctx)` first; skips the structure silently if no eligible antibody chains are found.
   - `antibody_cdr_sequences` — same eligibility gate; emits `abseq__cdr1/2/3_sequence` per antibody role.
   - `abepitope_score` — emits one grain=interface row per role-pair: `abepitope__score`, etc. Returns `available() = (False, reason)` if the abEpiTope package is absent.

   Each plugin accumulates output rows in a `TableBuffer`. When buffer memory exceeds the configured threshold, rows are spilled to a temporary parquet file on disk. After all structures are processed, the buffer is flushed to `_plugins/<name>/pdb.parquet`.

All plugin output columns are namespaced by prefix (e.g. `iface__`, `ifm__`, `abcdr__`). The registry rejects prefix collisions at startup.

### Step 4 — MERGE: LEFT JOIN plugins onto base rows

`merge_outputs(cfg)` produces the final `out_dir/pdb.parquet`:

1. Reads `_prepared/pdb.parquet` as the **base** — the grain rows produced by all QC and manipulation plugins.
2. For each plugin output in `_plugins/`, LEFT JOINs that plugin's `pdb.parquet` onto the base using the identity key columns (`path`, `assembly_id`, `grain`, plus `chain_id` / `role` / `pair` depending on grain). All base rows are always preserved. If a plugin did not emit a row for a given structure (because `available()` returned False), that structure's row gets `NaN` for all columns belonging to that plugin.
3. Writes the merged result to `out_dir/pdb.parquet`, plus `plugin_status.parquet` (counts of structures each plugin ran on) and `bad_files.parquet`.

After this step, `out_dir/pdb.parquet` is a single wide table where each row has identity columns, every QC/manipulation column, and every plugin column side-by-side.

### Step 5 — DATASET ANALYSIS: aggregate over the merged table

`analyze_dataset_outputs(out_dir)` reads `out_dir/pdb.parquet`, filters rows by `grain` using the column discriminator, and runs each configured `dataset_calculation` plugin:

- `interface_summary` — aggregates counts per interface pair (n_interfaces, mean contact atoms, unique sequence counts); writes rows to `dataset.parquet`.
- `cdr_entropy` — computes Shannon entropy of CDR loop sequences per role and region; writes per-region entropy rows to `dataset.parquet`.
- `cluster` — reads `iface__left_interface_residues` and `iface__right_interface_residues`, extracts Cα coordinates of interface residues from the prepared structures (reloading via `prepared__path` when `superimpose_to_reference` was used, so clustering runs on aligned coordinates), computes pairwise RMSD clusters, and **writes cluster labels back onto `out_dir/pdb.parquet`** as `cluster__left_cluster_id`, `cluster__left_mode`, `cluster__right_cluster_id`, `cluster__right_mode`.

The final state is: `out_dir/pdb.parquet` with cluster labels written back in, and `out_dir/dataset.parquet` with aggregate summary rows.

### What Persists

- Final `pdb.parquet`, `dataset.parquet`, `run_metadata.json`, `plugin_status.parquet`, and `bad_files.parquet` stay in `out_dir`.
- `_prepared/` stays under `out_dir` by default because `prepared__path` in `pdb.parquet` points into it. Deleting `_prepared/` before re-running dataset analyses means cluster can no longer reload the aligned structures.
- If you set `cleanup_prepared_after_dataset_analysis: true`, `_prepared/` is deleted only after dataset analysis completes successfully — use this on storage-constrained machines where you know you will not re-run dataset analyses.

## YAML keys at a glance

See [../README.md](/home/eva/minimum_atomworks/minimum_atw/examples/README.md) for the full flag glossary and on/off guidance.

Resource note:

- If you enable `abepitope_score`, `ablang2_score`, or `esm_if1_score`, set `gpu_workers` and usually `gpu_devices` in the YAML so the recorded scheduler metadata reflects a real GPU request.
- Rosetta, DockQ/pDockQ, clustering, and the post-merge dataset analyses remain CPU-oriented.

These simple-run YAMLs are the best starting point when:

- you want one config that can run end-to-end locally
- you want to iterate on one plugin with `prepare` + `run-plugin`
- you want to inspect intermediate outputs by turning on `keep_intermediate_outputs`
