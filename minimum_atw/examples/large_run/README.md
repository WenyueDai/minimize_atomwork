# Large Run Examples

This folder is for chunk-aware workflows:

- `run-chunked`
- `plan-chunks`
- `merge-planned-chunks`

## Files

- [example_antibody_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml)
- [example_vhh_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_vhh_antigen_chunked.yaml)
- [example_protein_protein_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_protein_protein_chunked.yaml)

## Run with internal chunk workers

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --workers 2
```

## Plan chunk configs for a scheduler

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli plan-chunks \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --plan-dir /home/eva/minimum_atomworks/out_antibody_antigen_chunk_plan
```

## What these configs show

- chunk-aware prepare and plugin execution
- `dataset_analysis_mode: post_merge` by default
- optional checkpoint settings
- optional Rosetta scaffold
- optional `cdr_entropy`
- enabled interface clustering

See [../README.md](/home/eva/minimum_atomworks/minimum_atw/examples/README.md) for the field glossary and flag guidance.

## Step By Step: What `run-chunked` Does

Using [example_antibody_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml) as the reference.

`minimum-atw run-chunked` calls `run_chunked_pipeline(cfg, chunk_size, workers)` which executes the full pipeline across N parallel workers and then merges the results. The four internal stages (PREPARE → EXECUTE → MERGE → DATASET ANALYSIS) are the same as a simple run — the difference is they run per-chunk in parallel before a final dataset-level merge and analysis.

### Step 1 — Config, discovery, and chunk planning

The CLI validates the YAML into `Config`. `discover_inputs(cfg.input_dir)` finds all `.pdb` and `.cif` files. `chunk_input_paths(paths, chunk_size)` splits the discovered list into groups of at most `chunk_size` structures. A `ProcessPoolExecutor(max_workers=workers)` is created (falling back to `ThreadPoolExecutor` if the process pool raises a `PermissionError` in restricted environments).

### Step 2 — Per-chunk input workspace

For each chunk, `prepare_chunk_input_dir(chunk_input_dir, paths)` creates a temporary directory and symlinks each structure file into it. Each chunk runs in full isolation — no shared file handles, no shared state. The chunk's `Config` is a copy of the source config with `input_dir` and `out_dir` overridden to the chunk's temporary workspace.

### Step 3 — PREPARE inside each chunk (runs in parallel)

Each chunk worker calls `prepare_outputs(chunk_cfg)` on its slice of structures:

1. Loads each structure into a biotite `AtomArray` and builds `Context(aa, chains, roles, config)`.
2. Runs **quality control** units (`prepare_section='quality_control'`):
   - `chain_continuity` — residue-ID gap and backbone-break check per chain; writes `continuity__n_breaks`, `continuity__has_break` (grain=chain).
   - `structure_clashes` — steric clash count; writes `clash__has_clash`, `clash__n_clashing_atom_pairs`, `clash__n_clashing_atoms` (grain=structure).
3. Runs **structure manipulation** units (`prepare_section='structure'`):
   - `center_on_origin` — translates `ctx.aa` to origin; records `center__centroid_x/y/z` and calls `ctx.rebuild_views()`.
   - `superimpose_to_reference` — fits `ctx.aa` onto the first structure in this chunk (or a fixed reference); mutates `ctx.aa` in place, calls `ctx.rebuild_views()`, records `sup__shared_atoms_rmsd`, `sup__anchor_atoms`, `sup__alignment_method`, `sup__coordinates_applied=True` (grain=structure) and `sup__rmsd`, `sup__matched_atoms` per shared chain (grain=chain).
4. Saves the transformed `ctx.aa` to `_prepared/structures/<name>.bcif`.
5. Writes `_prepared/pdb.parquet`, `_prepared/prepared_manifest.parquet`, and `_prepared/bad_files.parquet`.

Note: with `run-chunked`, the reference structure for `superimpose_to_reference` is the **first structure in each chunk's slice**, not a global first structure. For a globally consistent structural frame across chunks, provide an explicit `reference_path` in `plugin_params.superimpose_to_reference`.

### Step 4 — EXECUTE inside each chunk (runs in parallel)

`run_plugins(chunk_cfg, plugin_names)` runs within the same worker process as prepare. Plugins run sequentially in configured order. For each structure in the prepared manifest:

1. Reads the prepared `.bcif` from `_prepared/structures/` — always the aligned coordinates.
2. Rebuilds `Context` and runs each plugin's `run(ctx)`. Each plugin calls `available(ctx)` first; skips the structure silently if the check fails (e.g. `abepitope_score` when the package is absent, `antibody_cdr_lengths` when no antibody chain is found).
3. Plugin rows accumulate in a `TableBuffer`, spilling to disk when the memory threshold is crossed.
4. After all structures, each plugin flushes its buffer to `_plugins/<name>/pdb.parquet` in the chunk's temporary workspace.

### Step 5 — MERGE inside each chunk

`merge_outputs(chunk_cfg)` LEFT JOINs all `_plugins/<name>/pdb.parquet` onto `_prepared/pdb.parquet` using the identity key columns. Every base row is preserved; plugins that skipped a structure contribute `NaN` columns for that row. Writes `chunk_out_dir/pdb.parquet`, `plugin_status.parquet`, and `bad_files.parquet`.

Each chunk also writes `chunk_out_dir/run_metadata.json` containing the plugin list, role and interface-pair configuration, and row counts. This metadata is read during the final merge to validate cross-chunk compatibility.

### Step 6 — Final merge: STACK all chunk outputs

After all `ProcessPoolExecutor` futures complete, `merge_dataset_outputs([chunk_out_dirs], cfg.out_dir)` runs in the main process:

1. Reads `run_metadata.json` from each chunk and validates merge compatibility — same roles, interface pairs, assembly_id mode, and plugin set. Any mismatch raises an error before any stacking happens.
2. Concatenates each chunk's `pdb.parquet` row-wise (STACK, not JOIN). Global identity key uniqueness is enforced.
3. Assigns `dataset__id` and `dataset__name` columns from `cfg.dataset_annotations` onto every stacked row.
4. Writes `out_dir/pdb.parquet`, `plugin_status.parquet`, `bad_files.parquet`, and `dataset_metadata.json`.
5. Deletes each chunk's temporary workspace.

### Step 7 — DATASET ANALYSIS on the merged output

Because these configs use `dataset_analysis_mode: post_merge`, `analyze_dataset_outputs(cfg.out_dir)` runs once on the fully merged table — never per-chunk. This is the correct mode for clustering and entropy, which require the full population to produce meaningful results.

- `interface_summary` writes aggregate rows to `dataset.parquet`.
- `cdr_entropy` writes per-role, per-region Shannon entropy rows to `dataset.parquet`.
- `cluster` reads interface residue columns, reloads Cα coordinates from each row's `prepared__path` (the aligned prepared structure from that row's chunk), and writes cluster labels back onto `out_dir/pdb.parquet`.

Because the cluster plugin reloads structures through `prepared__path`, it uses the aligned prepared coordinates from whichever chunk produced each row. For globally consistent alignment across all chunks, use an explicit `reference_path` in the superimpose config (see Practical note below).

### What Persists

- Final `pdb.parquet`, `dataset.parquet`, `run_metadata.json`, `plugin_status.parquet`, and `bad_files.parquet` stay in `out_dir`.
- `_prepared/` from each chunk is kept under the chunk's temporary workspace until `run-chunked` finishes, then the temporary workspace is deleted. The final merged output does not include a `_prepared/` cache.
- If `prepared__path` values in the merged `pdb.parquet` point into the now-deleted temporary workspaces, later re-analysis using `analyze-dataset` will not be able to reload aligned structures. To preserve that capability, use `plan-chunks` + manual `run` + `merge-planned-chunks` with explicit `out_dir` values instead of `run-chunked`.
- If you set `cleanup_prepared_after_dataset_analysis: true`, the final `_prepared/` directory is deleted only after dataset analysis completes successfully.

Clustering behavior in the examples:

```yaml
dataset_analyses:
  - "cluster"
```

With no extra cluster params, chunked examples also emit both `left` and `right` jobs automatically.
Those cluster labels are written back onto interface rows in the merged `pdb.parquet`.

Because the chunked examples now use `superimpose_to_reference`, they are the most natural place to use coordinate-based dataset clustering on aligned prepared structures.

## Profiles

- antibody-antigen: heavy/light antibody binder against antigen
- VHH-antigen: single-chain binder against antigen
- protein-protein: generic non-antibody interface analysis

## Notes

- `dataset_analysis_mode: post_merge` is the cleanest default for clustering because clusters are only meaningful on the merged dataset.
- If you need per-chunk analyses for operational reasons, keep `cluster` commented out unless you explicitly want per-chunk cluster labels.
