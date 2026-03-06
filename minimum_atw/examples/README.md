# Examples

This folder contains runnable example configs for `minimum_atw` on this machine.

Use this Python environment for the commands below:

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python
```

Best commands to run first:

1. Simple end-to-end antibody-antigen run

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

This run includes `interface_contacts`, `antibody_cdr_lengths`, and `antibody_cdr_sequences`.
Because `numbering_roles` is configured, `interfaces.parquet` also includes antibody CDR contact columns such as:

- `iface__n_left_vh_cdr1_interface_residues`
- `iface__left_vh_cdr1_interface_residues`
- `iface__n_left_vl_cdr3_interface_residues`
- `iface__left_vl_cdr3_interface_residues`

2. Faster light run with fewer active plugins

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml
```

3. Automatic chunked run

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run-chunked \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 5 \
  --workers 2
```

4. Manual chunk example for debugging or staged execution

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml
```

Other ready-to-run configs:

- `/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_vhh_antigen.yaml`
- `/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/example_protein_protein_complex.yaml`
- `/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml`

More detail:

- [simple_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/simple_run/README.md)
- [chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md)
- [large_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md)
