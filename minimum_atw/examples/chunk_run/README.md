# Chunk Run Examples

This folder shows the manual chunk workflow.

For the preferred automatic workflow, use `run-chunked` on one config instead of creating chunk YAML files yourself.

Files:

- `chunk_antibody_antigen_01.yaml`
- `chunk_antibody_antigen_02.yaml`

Run the chunks:

```bash
python -m minimum_atw.cli run --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml
python -m minimum_atw.cli run --config minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml
```

Merge the finished chunk outputs:

```bash
python -m minimum_atw.cli merge-datasets \
  --out-dir /home/eva/minimum_atomworks/out_antibody_antigen_merged \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_01 \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_02
```

Then, if you want dataset-level summaries on the merged result, run:

```bash
python -m minimum_atw.cli analyze-dataset --config minimum_atw/examples/simple_run/example_antibody_antigen_pdb.yaml
```

Before running that analysis command, point `out_dir` in the YAML at:

```text
/home/eva/minimum_atomworks/out_antibody_antigen_merged
```

How this is intended to work:

- each chunk YAML writes a complete final `out_dir`
- chunk configs keep `dataset_analysis: false` to avoid redundant dataset summaries
- `merge-datasets` merges those final chunk outputs row by row into one new final `out_dir`
- dataset analysis is a separate step on the merged dataset

Adjust the chunk input directories and reference path to match your machine before running.

Automatic alternative:

```bash
python -m minimum_atw.cli run-chunked \
  --config minimum_atw/examples/simple_run/example_antibody_antigen_light.yaml \
  --chunk-size 5 \
  --workers 2
```

That command creates temporary chunks internally, runs them, merges the chunk outputs into the final `out_dir`, and removes the temporary chunk workspace afterward.
