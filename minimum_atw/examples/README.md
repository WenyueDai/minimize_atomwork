# Examples

Example configs for `minimum_atw`. Each YAML is self-contained and runnable.

## Quick start

```bash
# One-shot run (prepare → calculate → merge → dataset analyses)
python -m minimum_atw.cli run \
  --config minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
```

Or stage by stage:

```bash
CONFIG=minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml

python -m minimum_atw.cli prepare          --config "$CONFIG"
python -m minimum_atw.cli run-plugin       --config "$CONFIG" --plugin interface_metrics
python -m minimum_atw.cli merge            --config "$CONFIG"
python -m minimum_atw.cli analyze-dataset  --config "$CONFIG"
```

Python environment: `/home/eva/miniconda3/envs/atw_pp/bin/python`  
Working directory: `/home/eva/minimum_atomworks`

---

## Package model

Three plugin categories, three YAML keys:

| Category | YAML key | When it runs | What it does |
|---|---|---|---|
| `pdb_prepare` | `quality_controls` / `manipulations` | Prepare phase, per structure | Annotates or transforms each structure before calculations |
| `pdb_calculation` | `plugins` | Execute phase, per structure | Produces rows merged into `pdb.parquet` |
| `dataset_calculation` | `dataset_analyses` | After merge | Aggregates across the full dataset |

**Built-in prepare plugins:**

| Name | Key | What it does |
|---|---|---|
| `chain_continuity` | `quality_controls` | Flags residue-ID gaps and backbone breaks per chain |
| `structure_clashes` | `quality_controls` | Counts inter-chain atom clashes |
| `center_on_origin` | `manipulations` | Centers the structure's centroid at the origin |

**Built-in calculation plugins (`plugins:`):**

| Name | What it produces |
|---|---|
| `identity` | Atom/chain/residue counts per structure |
| `chain_stats` | Per-chain length and sequence stats |
| `role_sequences` | Per-role amino-acid sequence |
| `role_stats` | Per-role atom/residue counts |
| `interface_contacts` | Per-residue interface contacts |
| `interface_metrics` | Interface area, buried SASA, hydrogen bonds |
| `antibody_cdr_lengths` | CDR loop lengths (requires `numbering_roles`) |
| `antibody_cdr_sequences` | CDR loop sequences |
| `abepitope_score` | AbEpiTope epitope score (requires `hmmsearch`) |
| `superimpose_homology` | Per-structure RMSD to a reference structure |
| `rosetta_interface_example` | Rosetta InterfaceAnalyzer metrics (requires Rosetta) |

Plugin-specific config goes under `plugin_params`:

```yaml
plugin_params:
  superimpose_homology:
    reference_path: "/path/to/reference.pdb"
    on_chains: ["A", "B", "C"]
```

**Built-in dataset analyses (`dataset_analyses:`):**

| Name | What it produces |
|---|---|
| `dataset_annotations` | Copies `dataset_annotations` dict into `dataset.parquet` |
| `interface_summary` | Per-dataset interface residue statistics |
| `cluster` | Interface-residue clustering (writes back onto `pdb.parquet`) |
| `cdr_entropy` | Per-CDR sequence entropy across the dataset |

---

## Outputs

| File | Contents |
|---|---|
| `pdb.parquet` | All per-structure / per-chain / per-role / per-interface rows |
| `dataset.parquet` | Dataset-level analysis rows |
| `run_metadata.json` | Run config, counts, column manifest |
| `dataset_metadata.json` | Dataset analysis metadata |

The `grain` column in `pdb.parquet` discriminates row types:
`structure` · `chain` · `role` · `interface`

---

## Folders

- [simple_run/](simple_run/README.md) — one-shot local runs and plugin development
- [large_run/](large_run/README.md) — `run-chunked` and `plan-chunks` for large datasets
- [chunk_run/](chunk_run/README.md) — one-config-per-chunk manual workflows

### Simple run

| File | Profile |
|---|---|
| [example_antibody_antigen_light.yaml](simple_run/example_antibody_antigen_light.yaml) | Minimal antibody–antigen for dev/testing |
| [example_antibody_antigen_pdb.yaml](simple_run/example_antibody_antigen_pdb.yaml) | Full antibody–antigen (all native plugins) |
| [example_vhh_antigen.yaml](simple_run/example_vhh_antigen.yaml) | VHH (single-domain) against antigen |
| [example_protein_protein_complex.yaml](simple_run/example_protein_protein_complex.yaml) | Generic receptor–ligand |

### Large run (chunked)

| File | Profile |
|---|---|
| [example_antibody_antigen_chunked.yaml](large_run/example_antibody_antigen_chunked.yaml) | Antibody–antigen, `run-chunked` |
| [example_vhh_antigen_chunked.yaml](large_run/example_vhh_antigen_chunked.yaml) | VHH–antigen, `run-chunked` |
| [example_protein_protein_chunked.yaml](large_run/example_protein_protein_chunked.yaml) | Protein–protein, `run-chunked` |

### Manual chunk workflow

| File | Notes |
|---|---|
| [chunk_antibody_antigen_01.yaml](chunk_run/chunk_antibody_antigen_01.yaml) | Chunk 01 config |
| [chunk_antibody_antigen_02.yaml](chunk_run/chunk_antibody_antigen_02.yaml) | Chunk 02 config |
| [chunk_config_manifest_example.txt](chunk_run/chunk_config_manifest_example.txt) | Manifest for `merge-planned-chunks` |

---

## Minimal YAML reference

```yaml
input_dir: "./pdbs"
out_dir:   "./results"

roles:
  binder: ["A"]
  target: ["B"]
interface_pairs:
  - ["binder", "target"]

quality_controls:
  - "chain_continuity"
  - "structure_clashes"

manipulations:
  - "center_on_origin"

plugins:
  - "identity"
  - "interface_contacts"
  - "interface_metrics"
  - "superimpose_homology"

plugin_params:
  superimpose_homology:
    reference_path: "./reference.pdb"
    on_chains: ["A", "B"]

dataset_analyses:
  - "dataset_annotations"
  - "interface_summary"
  - "cluster"

dataset_annotations:
  project: "my_project"
```

## Clustering notes

`cluster` with no extra params emits `left` and `right` jobs automatically
(paratope and epitope for antibody runs). Cluster assignments are written back
onto `grain == "interface"` rows in `pdb.parquet`, not into `dataset.parquet`.

## Writing a new plugin

Copy [plugins/pdb/calculation/template/template_plugin.py](../plugins/pdb/calculation/template/template_plugin.py),
implement `run(ctx) -> Iterable[dict]`, add an instance to `_builtin_pdb_calculations()` in
[plugins/pdb/calculation/__init__.py](../plugins/pdb/calculation/__init__.py).

That's it — no base-class attributes required beyond `name` and `prefix`.
