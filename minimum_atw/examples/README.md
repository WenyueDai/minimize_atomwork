# minimum_atomworks — Examples

`minimum-atw` takes a folder of PDB/CIF structures and a YAML config, and
produces a single wide `pdb.parquet` table with per-structure, per-chain,
per-role, and per-interface metrics ready for analysis.

## Quick start — try it in 60 seconds

1. Copy `simple_run/example_antibody_antigen_light.yaml` to your working dir
2. Set your two paths:
   ```yaml
   input_dir: "/path/to/your/pdb_files"
   out_dir:   "/path/to/your/output"
   ```
3. Run:
   ```bash
   python -m minimum_atw.cli run --config example_antibody_antigen_light.yaml
   ```
4. Open `out_dir/pdb.parquet` in pandas.

When the same analysis outgrows one node, add `slurm.chunk_size` to that YAML and switch to:

```bash
python -m minimum_atw.cli submit-slurm --config example_antibody_antigen_light.yaml
```

---

## Which example should I start from?

| Situation | Use |
|---|---|
| Testing a plugin, prototyping, ≤ a few hundred structures | [`simple_run/`](simple_run/README.md) ← **start here** |
| One dataset, too large for a single process, want Slurm support | [`large_run/`](large_run/README.md) |
| Manual chunk control (one YAML per chunk, external scheduler) | [`chunk_run/`](chunk_run/README.md) |
| Multiple independent datasets to compare after merge | [`multi_dataset/`](multi_dataset/README.md) |

> *For most users: start at `simple_run`, move to `large_run` when you need scale.*

## Practical use cases

These are the main situations where you are likely to use `minimum_atw`, and
the example YAML that matches each one most directly.

| Use case | Start from this YAML |
|---|---|
| Minimal antibody-antigen ranking / QC on one dataset | [`simple_run/example_antibody_antigen_light.yaml`](simple_run/example_antibody_antigen_light.yaml) |
| Full antibody-antigen analysis without Rosetta | [`simple_run/example_antibody_antigen_pdb.yaml`](simple_run/example_antibody_antigen_pdb.yaml) |
| Full antibody-antigen analysis with Rosetta preprocess and InterfaceAnalyzer | [`simple_run/example_antibody_antigen_rosetta.yaml`](simple_run/example_antibody_antigen_rosetta.yaml) |
| Ready local smoke run on the bundled antibody-antigen example data | [`simple_run/example_antibody_antigen_realdata_all_non_rosetta.yaml`](simple_run/example_antibody_antigen_realdata_all_non_rosetta.yaml) |
| VHH / nanobody against antigen | [`simple_run/example_vhh_antigen.yaml`](simple_run/example_vhh_antigen.yaml) |
| Generic protein-protein complexes | [`simple_run/example_protein_protein_complex.yaml`](simple_run/example_protein_protein_complex.yaml) |
| Large antibody-antigen dataset on one node or Slurm | [`large_run/example_antibody_antigen_chunked.yaml`](large_run/example_antibody_antigen_chunked.yaml) |
| Large VHH-antigen dataset on one node or Slurm | [`large_run/example_vhh_antigen_chunked.yaml`](large_run/example_vhh_antigen_chunked.yaml) |
| Large protein-protein dataset on one node or Slurm | [`large_run/example_protein_protein_chunked.yaml`](large_run/example_protein_protein_chunked.yaml) |
| Manual fixed chunk boundaries | [`chunk_run/chunk_antibody_antigen_01.yaml`](chunk_run/chunk_antibody_antigen_01.yaml) and [`chunk_run/chunk_antibody_antigen_02.yaml`](chunk_run/chunk_antibody_antigen_02.yaml) |
| Compare two completed antibody-antigen datasets after merge | [`multi_dataset/dataset_a_antibody_antigen.yaml`](multi_dataset/dataset_a_antibody_antigen.yaml), [`multi_dataset/dataset_b_antibody_antigen.yaml`](multi_dataset/dataset_b_antibody_antigen.yaml), then [`multi_dataset/compare_merged_datasets.yaml`](multi_dataset/compare_merged_datasets.yaml) |

All of those are intended to be copy-and-edit YAMLs rather than internal-only
fixtures.

---

## Staged workflow

Every `run` call executes four stages. You can run them separately:

```bash
CONFIG=minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml

# Run all stages at once (most common)
python -m minimum_atw.cli run --config "$CONFIG"

# Or stage-by-stage (useful when iterating on one plugin)
python -m minimum_atw.cli prepare          --config "$CONFIG"
python -m minimum_atw.cli run-plugin       --config "$CONFIG" --plugin interface_contacts
python -m minimum_atw.cli merge            --config "$CONFIG"
python -m minimum_atw.cli analyze-dataset  --config "$CONFIG"
```

**Stage summary:**

| Stage | What it does | Output |
|---|---|---|
| `prepare` | Load structures, run QC, optionally superimpose | `_prepared/pdb.parquet`, cached `.bcif` files |
| `run-plugin` / `run-plugins` | Per-structure calculations, worker pools | `_plugins/<name>/pdb.parquet` |
| `merge` | LEFT JOIN all plugin tables onto base | `out_dir/pdb.parquet` |
| `analyze-dataset` | Aggregate across the merged table | `out_dir/dataset.parquet` |

`_prepared/` is a **cache boundary** — re-run `run-plugin` or `merge` without repeating prepare.

---

## Built-in plugins

### Prepare (manipulations list)
| Name | What it does |
|---|---|
| `chain_continuity` | Flag chain breaks |
| `structure_clashes` | Count steric clashes |
| `center_on_origin` | Recenter coordinates |
| `superimpose_to_reference` | Align all structures to a reference (coordinate rewrite) |
| `rosetta_preprocess` | Score → repack/relax → score → superimpose; set `rosetta_preprocess: false` to skip Rosetta steps and use as a plain superimpose |

`rosetta_preprocess` and `superimpose_to_reference` are mutually exclusive — both rewrite coordinates and perform superimposition, so only one should be listed in `manipulations` per run.

### Per-structure calculations (plugins list)
| Name | Grain | Notes |
|---|---|---|
| `identity` | structure / chain / role | Always enable |
| `chain_stats` | chain | Size, centroid, gyration |
| `role_sequences` | role | Sequences by chain |
| `role_stats` | role | Atom/residue counts |
| `interface_contacts` | interface | Contact atoms and residues |
| `interface_metrics` | interface | Residue-pair summaries, physicochemistry |
| `pdockq_score` | interface | pDockQ confidence |
| `dockq_score` | interface | DockQ vs native reference |
| `antibody_cdr_lengths` | role | CDR loop lengths (needs `abnumber`) |
| `antibody_cdr_sequences` | role | CDR sequences (needs `abnumber`) |
| `abepitope_score` | interface | AbEpiTope; **GPU-preferred** |
| `ablang2_score` | role | AbLang2 LL; **GPU-preferred** |
| `esm_if1_score` | role | ESM-IF1 LL; **GPU-preferred** |
| `rosetta_interface_example` | interface | Rosetta InterfaceAnalyzer; CPU |
| `superimpose_homology` | structure | Legacy RMSD plugin |

### Dataset analyses (dataset_analyses list)
| Name | What it produces |
|---|---|
| `dataset_annotations` | Metadata rows |
| `interface_summary` | Aggregated interface stats |
| `cluster` | Cluster labels written back onto interface rows |
| `cdr_entropy` | CDR sequence entropy |

---

## CPU vs GPU execution

### How it works

Three built-in plugins prefer a GPU: `abepitope_score`, `ablang2_score`, and `esm_if1_score`. All three accept `device: auto`, which checks `torch.cuda.is_available()` at startup and uses CUDA if a GPU is visible, otherwise falls back to CPU. The same YAML runs unmodified on a laptop (CPU) and on a GPU node (CUDA).

Under the hood, plugins are assigned to a **worker pool** (`cpu` or `gpu`). The scheduler groups compatible plugins and arranges them into **waves**. Pools within the same wave run concurrently; pools in different waves run sequentially.

### Local machine — CPU only (default)

```yaml
# gpu_workers: 0  ← default; no GPU pool created
cpu_workers: 4
```

All plugins run in a single CPU thread pool. GPU-capable plugins fall back to CPU via `device: auto`. Good for prototyping and small datasets.

### Local machine — mixed CPU + GPU

```yaml
cpu_workers: 4
gpu_workers: 1
gpu_devices: ["0"]     # CUDA device IDs visible to the GPU pool

plugin_params:
  abepitope_score:
    device: auto       # auto | cpu | cuda
  esm_if1_score:
    device: auto
  ablang2_score:
    device: auto
```

Two parallel worker pools run simultaneously: the CPU pool processes all CPU plugins across 4 threads while the GPU pool runs GPU plugins on device 0. They join at the merge stage.

> **Memory note**: `esm_if1_score` and `ablang2_score` each cache a large model. On a GPU with < 16 GB VRAM, enabling both may cause OOM. Either run them in separate passes or force one to `device: cpu`.

### HPC / Slurm — mixed mode

One Slurm job array. Each task handles one chunk and runs both CPU and GPU plugins inside the same allocation.

```yaml
slurm:
  chunk_size: 50
  mode: auto            # planner picks mixed when GPU cost is small relative to CPU
  sbatch_gpu_args:
    - "--partition=gpu"
    - "--gres=gpu:1"
    - "--mem=32G"
    - "--time=04:00:00"
```

```
array [chunk_000 … chunk_N]  ← prepare + CPU plugins + GPU plugins in one job
             ↓ afterok
single job: merge-planned-chunks
```

Use mixed when GPU nodes are cheap or GPU plugins are a small fraction of total runtime.

### HPC / Slurm — staged mode

Two separate Slurm arrays linked by `afterok`. CPU tasks prepare structures and run CPU plugins; GPU tasks read the cached `_prepared/` structures and run only GPU plugins on top.

```yaml
slurm:
  chunk_size: 50
  mode: staged          # or let mode: auto choose this when GPU cost dominates
  sbatch_cpu_args:
    - "--partition=cpu"
    - "--mem=16G"
    - "--time=04:00:00"
  sbatch_gpu_args:
    - "--partition=gpu"
    - "--gres=gpu:1"
    - "--mem=32G"
    - "--time=02:00:00"
  sbatch_merge_args:
    - "--partition=cpu"
    - "--mem=32G"
```

```
array (CPU stage) [chunk_000 … chunk_N]  ← prepare + CPU plugins
             ↓ --dependency=afterok
array (GPU stage) [chunk_000 … chunk_N]  ← GPU plugins only (reads _prepared/)
             ↓ --dependency=afterok
single job: merge-planned-chunks
```

Use staged when GPU nodes are scarce or expensive and you want to saturate cheap CPU nodes before queuing GPU work.

The planner (`mode: auto`) chooses between mixed and staged automatically. Check `chunk_plan.json → resource_plan.submission_plan.recommended_mode` to see which was chosen.

For the full story see [../../README.md — CPU vs GPU Execution](../../README.md).

---

## Full config key reference

### I/O
| Key | Default | When to set |
|---|---|---|
| `input_dir` | — | **Always** |
| `out_dir` | — | **Always** |
| `assembly_id` | `"1"` | Non-default assembly labels |
| `pdb_output_name` | `pdb.parquet` | Multiple runs in same out_dir |
| `dataset_output_name` | `dataset.parquet` | Multiple dataset outputs |

### Roles & interfaces
| Key | Default | When to set |
|---|---|---|
| `roles` | `{}` | **Always** — define antigen/antibody/binder roles |
| `interface_pairs` | `[]` | **Always** for interface work |

### Prepare
| Key | Default | When to set |
|---|---|---|
| `manipulations` | `[]` | Structure QC and/or superimposition |
| `clash_distance` | `2.0` | Non-default clash threshold (Å) |
| `clash_scope` | `all` | `inter_chain` or `interface_only` |

### Execution
| Key | Default | When to set |
|---|---|---|
| `plugins` | `[]` | **Always** |
| `contact_distance` | `5.0` | Non-default interface contact cutoff (Å) |
| `cpu_workers` | `1` | Optional override for CPU worker pool shape |
| `gpu_workers` | `0` | Optional override to expose a GPU worker pool |
| `gpu_devices` | `[]` | Optional CUDA device IDs, e.g. `["0", "1"]` |

### Resume / intermediate outputs
| Key | Default | When to set |
|---|---|---|
| `keep_intermediate_outputs` | `false` | Debugging, plugin iteration |
| `keep_prepared_structures` | `false` | Reuse aligned coordinates downstream |
| `checkpoint_enabled` | `false` | Long / preemptable runs |
| `checkpoint_interval` | `100` | Flush cadence when checkpointing |

### Antibody numbering
| Key | Default | When to set |
|---|---|---|
| `numbering_roles` | `[]` | Role names to treat as antibody chains |
| `numbering_scheme` | `imgt` | `chothia`, `kabat`, or `aho` |
| `cdr_definition` | `imgt` | `north` or `kabat` |

### Dataset analysis
| Key | Default | When to set |
|---|---|---|
| `dataset_analyses` | `[]` | Post-merge aggregations |
| `dataset_analysis_mode` | `post_merge` | `per_chunk` or `both` |
| `dataset_analysis_params` | `{}` | Per-analysis params dict |
| `dataset_annotations` | `{}` | Provenance metadata |
| `cleanup_prepared_after_dataset_analysis` | `false` | Save disk after finalised run |

### Chunked / Slurm
| Key | Default | When to set |
|---|---|---|
| `chunk_cpu_capacity` | auto | Override node CPU count for chunk concurrency |
| `slurm.chunk_size` | `null` | Required for the simple `submit-slurm --config your.yaml` path |
| `slurm.plan_dir` | derived from `out_dir` | Stable plan location for reuse or inspection |
| `slurm.mode` | `auto` | Force `mixed` or `staged` instead of planner-selected mode |
| `slurm.array_limit` | `null` | Limit concurrent tasks in the Slurm array |
| `slurm.sbatch_*_args` | `[]` | Cluster account / partition / memory / walltime policy grouped by common, mixed, CPU, GPU, and merge jobs |

### Rosetta
| Key | Default | When to set |
|---|---|---|
| `rosetta_executable` | auto-discovered | Path to `InterfaceAnalyzer`; required for `rosetta_interface_example` |
| `rosetta_database` | auto-discovered | Rosetta database dir; auto-found from executable path |
| `rosetta_score_jd2_executable` | auto-discovered | Path to `score_jd2`; required for `rosetta_preprocess` |
| `rosetta_relax_executable` | auto-discovered | Path to `relax`; required for `rosetta_preprocess` with `repack: true` or `relax: true` |
| `rosetta_preprocess` | `true` | Set `false` to skip Rosetta steps in the `rosetta_preprocess` manipulation (superimpose only) |
| `rosetta_interface_targets` | — | Role/chain-specific targets for `rosetta_interface_example` |
| `rosetta_pack_input`, `_separated`, `_compute_packstat` | `true` | Tune `rosetta_interface_example` scoring |

---

## Outputs

| File | Contents |
|---|---|
| `pdb.parquet` | All structure, chain, role, interface rows |
| `dataset.parquet` | Dataset-analysis rows |
| `run_metadata.json` | Run config, counts, scheduler resource hints |
| `plugin_status.parquet` | Per-plugin structure counts |
| `bad_files.parquet` | Structures that failed to load or QC |

### Key identity columns in `pdb.parquet`
| Column | Meaning |
|---|---|
| `path` | Source structure path |
| `grain` | `structure`, `chain`, `role`, or `interface` |
| `assembly_id` | Assembly label |
| `chain_id` / `role` / `pair` | Sub-identity for chain/role/interface rows |
| `dataset__id`, `dataset__name` | Provenance, copied from `dataset_annotations` |

---

## Notes

- Set `dataset_annotations.dataset_id` on every run you plan to merge later — `dataset__id` is copied onto every `pdb.parquet` row.
- For chunked workflows, `dataset_analysis_mode: post_merge` is the right default for clustering.
- `superimpose_to_reference` (prepare stage, rewrites coordinates) is the recommended superposition path. `superimpose_homology` (plugin stage, metrics only) is legacy.
- `rosetta_preprocess` replaces `superimpose_to_reference` when you want Rosetta relaxation before alignment. Do not enable both in the same run.
- Do not enable `superimpose_to_reference` / `rosetta_preprocess` together with `superimpose_homology` — they all write `sup__*` / `rosprep__*` columns that would conflict.
- `cluster` writes labels back onto `grain == "interface"` rows in `pdb.parquet`, not into `dataset.parquet`.
- `device: auto` is always safe. GPU-capable plugins resolve CUDA at startup if available and silently fall back to CPU otherwise — no YAML edits needed between environments.
