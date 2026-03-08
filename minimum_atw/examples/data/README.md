# examples/data/

Place your input PDB or CIF files here to run the example configs out of the box.

The example YAML files use `/path/to/your/pdb_files` as the `input_dir` placeholder.
Point that to this directory (or any directory containing your structures) before running.
The example YAMLs also include commented `cpu_workers`, `gpu_workers`, `gpu_devices`, and `chunk_cpu_capacity` hints so you can turn them into scheduler-ready templates for HPC.
For chunked HPC runs, the `large_run` examples can now be submitted directly with `minimum_atw.cli submit-slurm`.

## Suggested layout

```
examples/data/
  antibody_antigen/     # structures for simple_run antibody-antigen examples
  vhh_antigen/          # structures for VHH examples
  protein_protein/      # structures for protein-protein examples
  chunk_01/             # first slice for chunk_run examples
  chunk_02/             # second slice for chunk_run examples
  reference.pdb         # reference structure for superimpose_to_reference
```

## Getting test structures

Public antibody-antigen complexes are available from the [Protein Data Bank](https://www.rcsb.org/).
For antibody-antigen examples, any complex with distinct heavy chain, light chain, and antigen chains works.
Rename or assign chain IDs to match the `roles` in the YAML (default: `A` = antigen, `B` = VL, `C` = VH).

## Note on committed data

Runtime output (`pdb.parquet`, `dataset.parquet`, `run_metadata.json`, `_prepared/`, `out_*/`) should not be committed.
These paths are covered by `.gitignore` at the repo root.
