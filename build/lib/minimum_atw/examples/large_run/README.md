# Large Run Example

This folder is for automatic chunked execution with `run-chunked`.

Use:

```bash
python -m minimum_atw.cli run-chunked \
  --config minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --workers 4
```

What this does:

- reads one large `input_dir`
- splits the structures into temporary chunks
- runs chunks in parallel
- merges the final chunk outputs into the configured `out_dir`
- runs dataset analysis once on the merged result
- removes the temporary chunk workspace

Start with smaller values if you are unsure:

```bash
python -m minimum_atw.cli run-chunked \
  --config minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --workers 2
```
