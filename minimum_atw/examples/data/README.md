# examples/data/

Place your input PDB or CIF files here to run the example configs out of the box.

The example YAML files use `/path/to/your/pdb_files` as the `input_dir` placeholder.
Point that to this directory (or any directory containing your structures) before running.
For chunked HPC runs, prefer the `large_run` examples or add a small `slurm:` block with `chunk_size` to one of the other example YAMLs, then submit it with `minimum_atw.cli submit-slurm`.
The commented `cpu_workers`, `gpu_workers`, and `gpu_devices` fields are optional expert overrides rather than required setup.

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
