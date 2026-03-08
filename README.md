# minimum_atomworks

`minimum_atomworks` is a structural data-processing package for protein complexes.

It produces one unified PDB-side table plus optional dataset-level analysis output:

- `pdb.parquet`
- `dataset.parquet`

It is designed for:

- antibody-antigen complexes
- VHH or nanobody binders
- generic protein-protein complexes

The package is built around a simple idea:

1. prepare structures once
2. run PDB calculation plugins that add prefixed columns
3. merge into the final PDB parquet
4. optionally run dataset-level analyses

## Runtime Overview

Main pipeline:

- `prepare`
  load structures, run PDB and dataset prepare units, cache prepared structures when requested
- `pdb calculations`
  emit prefixed columns into unified PDB rows
- `merge`
  build final `pdb` output plus runtime metadata
- `dataset analyses`
  read merged `pdb` output and write `dataset` output

Large-dataset paths:

- `run-chunked`
  one larger job, internal chunk parallelism via `--workers`
- `plan-chunks` + `merge-planned-chunks`
  generate scheduler-ready chunk configs, run them externally, then merge
- `merge-datasets`
  stack already completed datasets, as long as they are compatible

Plugin execution planning can also separate CPU and GPU plugins into distinct worker pools.
Independent groups may run in different execution waves so CPU and GPU resources can be used at the same time.

![High-Level Runtime](minimum_atw/analysis/runtime.svg)

---

## Running a YAML — Full Walkthrough

This section follows one run from the moment you type the command to the moment the parquet files land in `out_dir`. It covers every configurable decision point, what each option does, and which case it is best suited for.

---

### Step 0 — Pick and configure a YAML

Every run starts from a YAML config. Pick the closest template from `examples/`:

| Template | Best for |
|---|---|
| `simple_run/example_antibody_antigen_light.yaml` | Quick start, no reference structure, CPU only |
| `simple_run/example_antibody_antigen_pdb.yaml` | Full antibody-antigen, superimpose, GPU plugins |
| `simple_run/example_vhh_antigen.yaml` | VHH / nanobody binders |
| `simple_run/example_protein_protein_complex.yaml` | Generic protein-protein, no CDR analysis |
| `large_run/example_antibody_antigen_chunked.yaml` | Large dataset, Slurm submission |

At minimum, set two paths in the YAML:

```yaml
input_dir: "/path/to/your/pdb_or_cif_files"
out_dir:   "/path/to/your/output_directory"
```

Then set roles and interface pairs to match your chain layout:

```yaml
roles:
  antigen:  ["A"]
  vh:       ["C"]
  vl:       ["B"]
  antibody: ["B", "C"]

interface_pairs:
  - ["antibody", "antigen"]
```

---

### Step 1 — Prepare stage

The prepare stage runs once per input structure, in the order listed in `manipulations`. Each manipulation mutates the in-memory structure (`ctx.aa`) so the next manipulation sees the already-modified coordinates. The final transformed structure is cached to `_prepared/structures/` for all subsequent plugin runs.

#### Quality control manipulations (always run first)

| Manipulation | What it does | Enable when |
|---|---|---|
| `chain_continuity` | Flags residue-index gaps and backbone breaks per chain; writes `continuity__*` columns | Almost always — catches broken models early |
| `structure_clashes` | Counts atom pairs closer than `clash_distance` (default 2 Å); writes `clash__*` columns | Almost always — catches steric errors |

Config options for QC:

```yaml
clash_distance: 2.0          # Å threshold; lower = stricter
clash_scope: "all"           # all | inter_chain | interface_only
```

#### Structure manipulations (run after QC, in listed order)

| Manipulation | What it does | Enable when |
|---|---|---|
| `center_on_origin` | Translates the whole complex so its centroid is at (0,0,0); writes `center__centroid_x/y/z` | Useful before superimposition or as a simple normalisation step |
| `superimpose_to_reference` | Aligns every structure's coordinates onto a reference PDB using `superimpose_homologs`; writes `sup__shared_atoms_rmsd`, per-chain `sup__rmsd`; **replaces coordinates in `_prepared/`** | When you have a crystal reference and want all models in the same structural frame |
| `rosetta_preprocess` | Runs Rosetta score → repack/relax → score again → then superimposes the relaxed structure to the reference; writes `rosprep__pre_*` (pre-relax scores), `rosprep__post_*` (post-relax scores), and the same superimpose metrics; set `rosetta_preprocess: false` to skip Rosetta and use as a plain superimpose | When you need Rosetta-relaxed structures before any analysis |

Key rules:
- `superimpose_to_reference` and `rosetta_preprocess` are **mutually exclusive** — both rewrite coordinates and superimpose, so only list one.
- Either superimpose manipulation sets `keep_prepared_structures: true` automatically so the aligned `_prepared/structures/` files persist.
- If no `reference_path` is given, the first structure in the run becomes the reference automatically.

Config for superimpose manipulations:

```yaml
manipulations:
  - name: "chain_continuity"
    grain: "pdb"
  - name: "structure_clashes"
    grain: "pdb"
  - name: "center_on_origin"
    grain: "pdb"
  - name: "superimpose_to_reference"   # or rosetta_preprocess
    grain: "pdb"

plugin_params:
  superimpose_to_reference:
    reference_path: "/path/to/reference.pdb"
    on_chains: ["A", "B", "C"]   # anchor chains for alignment
    # anchor_atoms: "CA"          # CA | backbone (default: CA)

  # rosetta_preprocess:
  #   reference_path: "/path/to/reference.pdb"
  #   on_chains: ["A", "B", "C"]
  #   repack: true    # sidechain-only fast optimisation (backbone fixed)
  #   relax: false    # full fast-relax including backbone (expensive)
```

Config for `rosetta_preprocess`:

```yaml
rosetta_preprocess: true   # false → skip Rosetta steps, behave like superimpose_to_reference
rosetta_score_jd2_executable: "/path/to/score_jd2.static.linuxgccrelease"  # auto-discovered if omitted
rosetta_relax_executable:    "/path/to/relax.static.linuxgccrelease"        # auto-discovered if omitted
rosetta_database:            "/path/to/rosetta/database"                    # auto-discovered if omitted
```

#### Prepare output

```
_prepared/
  pdb.parquet               ← prepare-stage rows for all manipulations
  prepared_manifest.parquet ← source_path → prepared_path mapping
  structures/               ← cached transformed structure files (if keep_prepared_structures: true)
```

---

### Step 2 — Plugin execution stage

Plugins run on the prepared structures (always aligned coordinates when superimpose is enabled). The scheduler groups them into **CPU** and **GPU** worker pools, which run concurrently when both are active.

#### Plugin selection

Enable only the plugins you need. Each plugin appends prefixed columns to the output:

| Plugin | Grain | Prefix | Key outputs | Requires |
|---|---|---|---|---|
| `identity` | structure/chain/role | `id__` | atom/residue counts, B-factor | — |
| `chain_stats` | chain | `chstat__` | length, centroid, radius of gyration | — |
| `role_sequences` | role | `rolseq__` | per-role sequence strings | — |
| `role_stats` | role | `rolstat__` | atom/residue counts per role | — |
| `antibody_cdr_lengths` | role | `abcdr__` | CDR1/2/3 lengths | `abnumber` |
| `antibody_cdr_sequences` | role | `abseq__` | CDR1/2/3 sequences | `abnumber` |
| `interface_contacts` | interface | `iface__` | contact atom pairs, CDR contact flags | — |
| `interface_metrics` | interface | `ifm__` | polar/apolar counts, H-bonds, physicochemistry | — |
| `pdockq_score` | interface | `pdockq__` | pDockQ confidence score | — |
| `dockq_score` | interface | `dockq__` | DockQ Fnat/LRMS/iRMS vs native | reference PDB |
| `abepitope_score` | interface | `abepitope__` | epitope probability score | `abepitope`, `hmmsearch` |
| `ablang2_score` | role | `ablang2__` | antibody log-likelihood per role | `ablang2`, `torch` |
| `esm_if1_score` | role | `esm__` | ESM-IF1 log-likelihood per role | `fair-esm`, `torch` |
| `rosetta_interface_example` | interface | `rosetta__` | dG, dSASA, packstat, hbonds | Rosetta binaries |

For `dockq_score`, the reference path must be set:

```yaml
plugin_params:
  dockq_score:
    reference_path: "/path/to/native_complex.pdb"
    receptor_role: "antigen"   # role to superimpose on for LRMS
    contact_distance: 5.0
```

For antibody CDR plugins, numbering must be configured:

```yaml
numbering_roles: ["vh", "vl"]    # which roles to number
numbering_scheme: "imgt"         # imgt | chothia | kabat | aho
cdr_definition: "imgt"           # imgt | north | kabat
```

#### Worker pool configuration

| Config | Default | What it controls |
|---|---|---|
| `cpu_workers` | `1` | Number of parallel CPU worker threads |
| `gpu_workers` | `0` | Number of GPU worker slots; `0` = no GPU pool, GPU plugins fall back to CPU |
| `gpu_devices` | `[]` | CUDA device IDs to expose, e.g. `["0"]` or `["0", "1"]` |

```yaml
# CPU only — GPU plugins run on CPU via device: auto
cpu_workers: 4
gpu_workers: 0

# Mixed — GPU plugins use CUDA device 0 concurrently with CPU pool
cpu_workers: 4
gpu_workers: 1
gpu_devices: ["0"]
```

All three GPU-capable plugins accept a `device` param:

```yaml
plugin_params:
  abepitope_score:
    device: auto    # auto | cpu | cuda | 0 (default: auto)
  esm_if1_score:
    device: auto
    on_roles: []    # restrict to specific roles, e.g. ["vh", "vl"]; [] = all roles
  ablang2_score:
    device: auto
    on_roles: []
```

`device: auto` is always safe to leave on — it resolves CUDA at startup if available, otherwise CPU.

#### Checkpoint / resume

For long runs on preemptable nodes:

```yaml
checkpoint_enabled: true
checkpoint_interval: 25   # flush to disk every N structures
```

If the job is killed, re-run the same command — prepare and plugin stages will pick up from the last checkpoint.

---

### Step 3 — Merge stage

Automatic. No config needed.

Reads `_prepared/pdb.parquet` (the base identity rows — one structure row + chain rows + role rows + interface rows per input file), then LEFT JOINs every `_plugins/<name>/pdb.parquet` onto it by the identity key columns `(path, assembly_id, grain, chain_id, role, pair)`. Plugins that skipped a structure contribute `NaN` for that row. Writes `out_dir/pdb.parquet`.

---

### Step 4 — Dataset analysis stage

Runs once on the merged `pdb.parquet`. Enable what you need:

| Analysis | What it writes | Best for |
|---|---|---|
| `dataset_annotations` | Provenance metadata rows to `dataset.parquet` | Always enable — records dataset_id, project, modality |
| `interface_summary` | Aggregate interface stats (mean dG, contact counts, etc.) to `dataset.parquet` | When you want a dataset-level summary table |
| `cluster` | RMSD-based cluster labels written back onto `pdb.parquet` interface rows | When comparing many models in a structural ensemble |
| `cdr_entropy` | Shannon entropy per CDR position to `dataset.parquet` | When analysing sequence diversity across a panel |

When to run it:

```yaml
dataset_analysis_mode: "post_merge"   # run once after all chunks are merged (recommended for cluster/entropy)
# dataset_analysis_mode: "per_chunk"  # run on each chunk independently (faster feedback, less meaningful for cluster)
# dataset_analysis_mode: "both"       # run per chunk AND after merge
```

Provenance:

```yaml
dataset_annotations:
  dataset_id: "my_run_01"      # required if you plan to merge datasets later
  dataset_name: "my_run_01"
  project: "my_project"
  modality: "antibody_antigen"
```

---

### Step 5 — Choosing a run command

This is where local and HPC paths diverge.

#### Option A — One-shot local run (≤ a few hundred structures)

```bash
python -m minimum_atw.cli run --config my_config.yaml
```

Runs all four stages sequentially in one process. Everything stays in memory between stages. The fastest path for small datasets.

**Best for**: prototyping, single-workstation runs, < ~500 structures.

#### Option B — Staged local run (debugging / iterating on one plugin)

```bash
python -m minimum_atw.cli prepare         --config my_config.yaml
python -m minimum_atw.cli run-plugin      --config my_config.yaml --plugin interface_contacts
python -m minimum_atw.cli merge           --config my_config.yaml
python -m minimum_atw.cli analyze-dataset --config my_config.yaml
```

The prepare stage writes `_prepared/` once. You can then re-run `run-plugin` with a different plugin or edited params and re-merge without re-preparing. Use `keep_intermediate_outputs: true` to keep `_plugins/` between runs.

**Best for**: iterating on plugin params, debugging a single plugin, re-running analysis with different cluster settings.

#### Option C — Internal chunked run (one machine, large dataset)

```bash
python -m minimum_atw.cli run-chunked \
  --config my_config.yaml \
  --chunk-size 50 \
  --workers 4
```

Splits the input into chunks of 50 structures, runs up to 4 chunks in parallel (subject to CPU/GPU budget constraints), then stacks the outputs and runs dataset analysis once. Each chunk is a full mini-pipeline (prepare → execute → merge). Temporary chunk workspaces are deleted after the final stack.

```yaml
# In the YAML, set worker pool shape per chunk:
cpu_workers: 4      # threads per chunk
gpu_workers: 1      # GPU slots per chunk
gpu_devices: ["0"]
```

**Best for**: one powerful workstation or single HPC node, dataset too large for one process, no job scheduler needed.

**Trade-off**: `_prepared/` paths in the final merged parquet point into deleted temp dirs, so `analyze-dataset` with reloading (e.g. clustering) cannot re-run afterwards. If you need that, use Option D or E instead.

#### Option D — Planned chunks + manual execution (full control)

```bash
# 1. Generate one YAML per chunk + resource hints
python -m minimum_atw.cli plan-chunks \
  --config my_config.yaml \
  --chunk-size 50 \
  --plan-dir /path/to/chunk_plan

# 2. Run each chunk independently (e.g. as Slurm array tasks)
python -m minimum_atw.cli run --config /path/to/chunk_plan/chunk_0000.yaml
python -m minimum_atw.cli run --config /path/to/chunk_plan/chunk_0001.yaml
# ...

# 3. Merge after all chunks finish
python -m minimum_atw.cli merge-planned-chunks \
  --plan-dir /path/to/chunk_plan \
  --out-dir /path/to/final_out
```

`plan-chunks` writes `chunk_plan.json` which includes `resource_plan` with per-wave CPU/GPU demand, recommended job shapes, and the maximum safe concurrency. Inspect it before submitting:

```
chunk_plan.json
  resource_plan.recommended_chunk_job   ← one mixed job request
  resource_plan.submission_plan         ← staged CPU + GPU job shapes
  resource_plan.max_concurrent_chunks   ← safe concurrency on this node budget
```

Unlike `run-chunked`, each chunk's `_prepared/` directory is preserved in its own `out_dir`. `prepared__path` values in the final merged parquet remain valid, so you can re-run `analyze-dataset` with different settings later.

**Best for**: HPC with a custom scheduler, when you want full control over job submission, when you need `_prepared/` to persist.

#### Option E — One-command Slurm submission (recommended for HPC)

Add a `slurm:` block to the YAML:

```yaml
slurm:
  chunk_size: 50
  mode: auto        # auto | mixed | staged (see below)
  sbatch_common_args:
    - "--account=my_lab"
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
    - "--time=01:00:00"
```

Then submit:

```bash
python -m minimum_atw.cli submit-slurm --config my_config.yaml --dry-run
# remove --dry-run to actually call sbatch
```

`submit-slurm` runs `plan-chunks` internally, then submits the Slurm jobs automatically with the right `afterok` dependencies.

**`mode: auto`** — the planner inspects the plugin list and picks the best mode:

- **`mixed`** — one job array, each task runs CPU + GPU plugins inside the same allocation.

  ```
  sbatch array [chunk_000 … chunk_N]   ← prepare + CPU + GPU in one job
                    ↓ afterok
  sbatch single: merge-planned-chunks
  ```

  Best when: GPU nodes are plentiful, GPU plugins are a small fraction of runtime, or the dataset is small.

- **`staged`** — two job arrays linked by `afterok`. CPU array runs first (prepare + CPU plugins), GPU array runs after (GPU plugins only, reads `_prepared/`).

  ```
  sbatch array (CPU) [chunk_000 … chunk_N]   ← prepare + CPU plugins
                    ↓ afterok
  sbatch array (GPU) [chunk_000 … chunk_N]   ← GPU plugins only
                    ↓ afterok
  sbatch single: merge-planned-chunks
  ```

  Best when: GPU allocations are expensive or scarce; you want CPU nodes to saturate first before using GPU quota.

Force a specific mode by setting `mode: mixed` or `mode: staged` in the YAML or with `--mode` on the command line.

---

### Decision guide

```
How many structures?
├── ≤ a few hundred → Option A: python -m minimum_atw.cli run
├── hundreds to thousands, one machine → Option C: run-chunked
└── thousands+, HPC cluster
    ├── GPU nodes cheap or GPU plugins minor → Option E, mode: mixed
    ├── GPU nodes scarce or expensive → Option E, mode: staged
    └── Need full control / custom scheduler → Option D: plan-chunks + manual

Need to iterate on plugins without re-preparing?
└── Option B: staged local run (prepare once, re-run run-plugin + merge)

Need _prepared/ to persist for later re-analysis?
└── Option D or E (NOT run-chunked — it deletes temp chunk workspaces)
```

---

## CPU vs GPU Execution — What Happens Behind the Scenes

### How plugins are assigned to pools

Every plugin carries a `worker_pool` attribute — either `"cpu"` (the default) or `"gpu"`. The three GPU-capable built-in plugins (`abepitope_score`, `esm_if1_score`, `ablang2_score`) set `worker_pool = "gpu"` at class definition time. The actual hardware they use is resolved later at runtime via their `device: auto` parameter:

- `device: auto` → check `torch.cuda.is_available()` at the start of the run; use CUDA if a GPU is visible, CPU otherwise.
- `device: cpu` / `device: cuda` → force explicitly regardless of hardware.

Because of `auto`, the same YAML works on a laptop (falls back to CPU) and on a GPU node (uses CUDA) without any edits.

### Plugin scheduling: groups and waves

Before any structure is processed, the scheduler groups plugins into **groups** by compatibility (`worker_pool`, `execution_mode`, `input_model`, `max_workers`). It then packs groups into sequential **waves** such that:

- groups in the **same wave** run **concurrently** (their pools run in parallel threads/processes);
- groups in **different waves** run **sequentially** (a wave starts only after the previous wave finishes).

In practice with the default built-in plugins:

```
Wave 0 — CPU pool: identity, chain_stats, role_sequences, role_stats,
          antibody_cdr_lengths, antibody_cdr_sequences,
          interface_contacts, interface_metrics, pdockq_score, dockq_score

Wave 1 — GPU pool: abepitope_score, esm_if1_score, ablang2_score
```

Wave 0 and Wave 1 do **not** overlap because the GPU plugins are placed in the next wave — the CPU pool completes first. If you had plugins that could run concurrently in the same wave with different pools, they would overlap.

---

### Local machine — CPU only (`gpu_workers: 0`, the default)

```yaml
cpu_workers: 4   # 4 parallel worker threads
gpu_workers: 0   # no GPU pool
```

All plugins execute in a single CPU thread pool. `cpu_workers` controls how many structures are processed simultaneously. GPU-capable plugins (`abepitope_score` etc.) fall back to CPU execution via `device: auto`. There is no wave separation — everything runs in one pool sequentially through the plugin list.

**When to use**: prototyping, small datasets (< a few hundred structures), machines without a GPU.

---

### Local machine — mixed CPU + GPU (`gpu_workers: 1`)

```yaml
cpu_workers: 4
gpu_workers: 1
gpu_devices: ["0"]   # which CUDA device(s) to expose
```

The scheduler creates two parallel worker pools:

1. **CPU pool** (4 threads) — runs `identity`, `chain_stats`, `interface_contacts`, `pdockq_score`, etc.
2. **GPU pool** (1 worker pinned to CUDA device 0) — runs `abepitope_score`, `esm_if1_score`, `ablang2_score`.

Both pools process the full structure list independently and concurrently. The CPU pool does not wait for the GPU pool to finish a structure before starting the next one. The two pools are joined at the merge stage.

**When to use**: workstation with one GPU; you want maximum throughput without a scheduler.

**Memory note**: `esm_if1_score` and `ablang2_score` each cache a large model. If both are enabled on a small GPU (< 16 GB), they may exceed VRAM. Either run them in separate passes or use `device: cpu` for one of them.

---

### HPC / Slurm — mixed mode (one job array)

```yaml
slurm:
  chunk_size: 50
  mode: auto        # planner picks mixed when GPU demand is low
  sbatch_gpu_args:
    - "--partition=gpu"
    - "--gres=gpu:1"
    - "--mem=32G"
```

`submit-slurm` generates **one Slurm job array** where each task handles one chunk. Each task runs both the CPU and GPU plugin pools inside the same allocation. The GPU-capable plugins load models onto whichever CUDA device is visible to the task.

```
sbatch array:  [chunk_000, chunk_001, ..., chunk_N]   ← each task: CPU + GPU in same job
                        ↓ afterok
sbatch single: merge-planned-chunks
```

**When to use**: GPU nodes are plentiful, each chunk is small enough that one GPU allocation is cheap, or GPU-capable plugins are a small fraction of runtime.

---

### HPC / Slurm — staged mode (separate CPU and GPU arrays)

```yaml
slurm:
  chunk_size: 50
  mode: staged      # or let planner pick when GPU demand dominates
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

`submit-slurm` generates **two separate arrays** linked by Slurm `afterok` dependencies:

```
sbatch array (CPU stage):  [chunk_000, ..., chunk_N]  ← prepare + CPU plugins only
        ↓ --dependency=afterok:<cpu_array_id>
sbatch array (GPU stage):  [chunk_000, ..., chunk_N]  ← GPU plugins only (reads _prepared/)
        ↓ --dependency=afterok:<gpu_array_id>
sbatch single: merge-planned-chunks
```

- CPU tasks: prepare + all `worker_pool="cpu"` plugins. Each structure's prepared coordinates are cached to `_prepared/structures/` at this stage.
- GPU tasks: read the already-prepared structures and run only the GPU-pool plugins on top. No re-preparation.

**When to use**: GPU nodes are scarce or expensive; you want to saturate cheap CPU nodes first and queue GPU tasks only after the expensive prepare phase finishes. Typical for clusters where GPU allocations are limited.

The planner (`mode: auto`) picks staged automatically when the GPU plugin fraction of total runtime is expected to justify separate allocations. Inspect `chunk_plan.json → resource_plan.submission_plan.recommended_mode` to see which mode it chose and why.

---

### Summary table

| Setting | Hardware used | Pool model | Typical use |
|---|---|---|---|
| `gpu_workers: 0` (default) | CPU only | Single thread pool | Laptop, small datasets |
| `gpu_workers: 1` | CPU + GPU | Two parallel pools | Workstation with 1 GPU |
| Slurm `mode: mixed` | CPU + GPU per task | One array, both in same job | GPU nodes are cheap |
| Slurm `mode: staged` | CPU array then GPU array | Two arrays with `afterok` | GPU nodes are scarce |

**`device: auto` is always safe to leave on.** The plugin resolves the right backend at startup — CUDA on a GPU node, CPU everywhere else — so you never need to edit the YAML between environments.

## Architecture Overview

The package has three internal layers:

- [minimum_atw/core](/home/eva/minimum_atomworks/minimum_atw/core)
  config, row-identity rules, registries, orchestration
- [minimum_atw/runtime](/home/eva/minimum_atomworks/minimum_atw/runtime)
  execution mechanics, chunk planning, workspace layout, spill buffers
- [minimum_atw/plugins](/home/eva/minimum_atomworks/minimum_atw/plugins)
  PDB and dataset extension implementations

Public entrypoints:

- [minimum_atw/__init__.py](/home/eva/minimum_atomworks/minimum_atw/__init__.py)
- [minimum_atw/cli.py](/home/eva/minimum_atomworks/minimum_atw/cli.py)

![High-Level Architecture](minimum_atw/analysis/architecture.svg)

Module-level code layout:

![Module Layer Map](minimum_atw/analysis/module_layers.svg)

Plugin scheduling — how groups and waves are assigned:

![Plugin Wave Scheduler](minimum_atw/analysis/plugin_wave_scheduler.svg)


Current plugin taxonomy:

- `pdb/quality_control`
- `pdb/manipulation`
- `pdb/calculation`
- `dataset/quality_control`
- `dataset/manipulation`
- `dataset/calculation`

## PDB Table

The final PDB parquet stores all PDB-side outputs together. Row grain is encoded in `grain`:

- `structure`
- `chain`
- `role`
- `interface`

Identity columns:

- `path`
- `assembly_id`
- `grain`
- `chain_id`
- `role`
- `pair`
- `role_left`
- `role_right`

Plugin outputs are merged by identity keys. Non-identity fields are prefixed:

```text
<prefix>__<field>
```

Examples:

- `id__n_atoms_total`
- `iface__n_contact_atom_pairs`
- `abseq__cdr3_sequence`
- `abepitope__score`

Internal helper modules such as [interface_metrics.py](/home/eva/minimum_atomworks/minimum_atw/plugins/pdb/calculation/interface_analysis/interface_metrics.py) support plugins but are not themselves YAML-selectable extensions.

Most dataset analyses write a second parquet, usually `dataset.parquet`, with an `analysis` column instead of `grain`. Dataset-level clustering is the main exception: it is computed at dataset scope but writes its assignments back onto `pdb.parquet` interface rows.

## Installation

Recommended reproducible setup for a fresh machine:

```bash
git clone <your-repo-url> minimum_atomworks
cd minimum_atomworks
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e '.[all]'
```

That installs:

- core runtime dependencies
- antibody numbering support: `abnumber`, `anarcii`
- GPU/model plugins: `torch`, `fair-esm`, `ablang2`
- AbEpiTope Python package

External dependency still required for `abepitope_score`:

```bash
conda install -c bioconda hmmer
```

`hmmsearch` must be on `PATH` for AbEpiTope when chain hints cannot be derived from roles.

If you do not want the full stack, install one of these instead:

```bash
python -m pip install -e .              # core only
python -m pip install -e '.[antibody]'  # abnumber + anarcii
python -m pip install -e '.[esm]'       # torch + fair-esm for esm_if1_score
python -m pip install -e '.[ablang2]'   # ablang2 + torch
python -m pip install -e '.[abepitope]' # abepitope + torch + fair-esm
```

Verify the environment:

```bash
python -m minimum_atw.cli list-extensions
python - <<'PY'
from importlib.util import find_spec
mods = ["abnumber", "anarcii", "ablang2", "torch", "esm", "abepitope"]
for name in mods:
    print(name, bool(find_spec(name)))
PY
which hmmsearch || echo "hmmsearch not found"
```

Notes:

- `abepitope_score` needs both the Python package and the external `hmmsearch` binary
- `esm_if1_score` needs `torch` and `fair-esm`
- `ablang2_score` needs `ablang2`
- on a GPU machine, also confirm `python -c "import torch; print(torch.cuda.is_available())"` returns `True` if you expect CUDA execution
- Rosetta is not installed by this package
- example YAMLs usually need path edits before reuse on another machine

## Common Commands

One-shot run:

```bash
python -m minimum_atw.cli run --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

Staged run:

```bash
python -m minimum_atw.cli prepare --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
python -m minimum_atw.cli run-plugin --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml --plugin identity
python -m minimum_atw.cli merge --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
python -m minimum_atw.cli analyze-dataset --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

Automatic chunked run:

```bash
python -m minimum_atw.cli run-chunked \
  --config minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --workers 4
```

Scheduler-ready chunk planning:

```bash
python -m minimum_atw.cli plan-chunks \
  --config minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --plan-dir /path/to/chunk_plan
```

Merge planned chunks:

```bash
python -m minimum_atw.cli merge-planned-chunks --plan-dir /path/to/chunk_plan
```

Merge completed datasets:

```bash
python -m minimum_atw.cli merge-datasets \
  --out-dir /path/to/merged_out \
  --source-out-dir /path/to/out_a \
  --source-out-dir /path/to/out_b
```

## Output Layout

Final outputs in `out_dir/`:

- configured PDB parquet, `pdb.parquet` by default
- `run_metadata.json`

Dataset-level outputs:

- configured dataset parquet, `dataset.parquet` by default
- `dataset_metadata.json`

Optional naming keys in YAML:

- `pdb_output_name: 20250212_pdb.parquet`
- `dataset_output_name: 20250212_dataset.parquet`

Failure/debug output:

- `plugin_status.parquet` is only written for intermediate/checkpointed runs or when any plugin status is non-`ok`
- `bad_files.parquet` is only written when failures occur
- `_prepared/` and flat `_plugins/` artifacts are only kept when `keep_intermediate_outputs: true`

`run_metadata.json` and `dataset_metadata.json` also record `output_files` so downstream tools can resolve custom parquet names reliably. `run_metadata.json` now also includes `plugin_execution.scheduler_resources`, which summarizes both the peak single-job CPU/GPU demand and a staged submission plan for splitting CPU-only and GPU-enabled phases on HPC.

## Merge Compatibility

Datasets should only be merged if they represent the same analysis setup.

`merge-datasets` checks:

- recorded runtime compatibility
- final table-column compatibility

So merges are expected to fail if datasets differ in important settings such as:

- active plugins
- prepare-stage semantics
- interface settings
- antibody numbering settings like `numbering_scheme` or `cdr_definition`
- final parquet schema

Output filenames do not affect merge compatibility. Different runs can still merge as long as the actual schema and runtime settings match.

## Examples

Start here:

- [examples/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/README.md)

Detailed guides:

- [simple_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/README.md)
- [chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md)
- [large_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md)

YAML config field meanings:

- [examples/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/README.md)

## Tests

Tests live under:

- [minimum_atw/tests](/home/eva/minimum_atomworks/minimum_atw/tests)

Run them with:

```bash
cd /home/eva/minimum_atomworks
/home/eva/miniconda3/envs/atw_pp/bin/python -m unittest discover -s minimum_atw/tests -v
```

Detailed test instructions:

- [minimum_atw/tests/README.md](/home/eva/minimum_atomworks/minimum_atw/tests/README.md)
