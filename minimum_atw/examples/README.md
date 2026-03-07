# Examples

This folder contains the maintained example configs for the current `minimum_atw` package layout.

Current package model:

- `pdb/quality_control`
- `pdb/manipulation`
- `pdb/calculation`
- `dataset/quality_control`
- `dataset/manipulation`
- `dataset/calculation`

Current final outputs:

- one PDB-side parquet: `pdb.parquet` by default
- one dataset-side parquet: `dataset.parquet` by default
- `run_metadata.json`
- `dataset_metadata.json`

You may override the parquet filenames in YAML with:

```yaml
# pdb_output_name: "20250307_pdb.parquet"
# dataset_output_name: "20250307_dataset.parquet"
```

Use this Python environment:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python
```

Run commands from:

```bash
cd /home/eva/minimum_atomworks
```

## Folders

- [simple_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/README.md): one-shot local runs and plugin development
- [large_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md): `run-chunked` and `plan-chunks`
- [chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md): one-config-per-chunk manual workflows

## Example policy

- Built-in QC and native PDB/interface plugins are enabled when they fit the profile.
- Rosetta remains scaffolded but commented out by default.
- AbEpiTope is enabled in antibody-oriented examples.
- `cdr_entropy` is scaffolded but off by default.
- `cluster` is enabled by default in all examples.

## Dataset analyses in the examples

Enabled by default:

- `dataset_annotations`
- `interface_summary`
- `cluster`

Optional and commented out:

- `cdr_entropy`

Current clustering surface is interface-focused, and the default is already “both sides”:

```yaml
dataset_analyses:
  - "cluster"
```

Interpretation:

- with no extra `dataset_analysis_params.cluster` block, the plugin emits two jobs:
  - `left`
  - `right`
- dataset scope is used only to compute the clusters
- the assignments are written back onto `pdb.parquet` on `grain == "interface"`
- `right` means the right side of each configured interface pair
- `left` means the left side

For antibody-antigen examples with `["antibody", "antigen"]`:

- `right` means antigen epitope clustering
- `left` means antibody paratope clustering

This clustering uses symmetric Chamfer distance on interface-residue `CA` point clouds. It is most meaningful when the dataset has already been placed in a comparable frame, which is why the antibody-oriented examples keep `superimpose_homology` scaffolded and configured.

If you want explicit names like `epitope` and `paratope` instead of `right` and `left`, you can still override the default with a `cluster.jobs` block.

## Ready-to-run local examples

- [example_antibody_antigen_light.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml)
- [example_antibody_antigen_pdb.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml)
- [example_vhh_antigen.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml)
- [example_protein_protein_complex.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml)

## Chunk-aware examples

- [example_antibody_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml)
- [example_vhh_antigen_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_vhh_antigen_chunked.yaml)
- [example_protein_protein_chunked.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_protein_protein_chunked.yaml)

## Manual chunk examples

- [chunk_antibody_antigen_01.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml)
- [chunk_antibody_antigen_02.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml)
- [chunk_config_manifest_example.txt](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_config_manifest_example.txt)
