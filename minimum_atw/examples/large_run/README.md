# Large Run Example

This folder is for automatic chunked execution with `run-chunked`.

Use:

```bash
python -m minimum_atw.cli run-chunked \
  --config minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --workers 4
```

Staged large-run pattern:

`run-chunked` is already an orchestrated command, so there is no separate `prepare -> run-plugin -> merge` chain for the whole dataset. The closest staged workflow is:

1. run the same config with smaller `chunk-size` and `workers` first
2. inspect the final merged output
3. rerun with the production chunk size and worker count

Example dry run:

```bash
python -m minimum_atw.cli run-chunked \
  --config minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --workers 2
```

If you need full manual staging, use the chunk YAML workflow in [chunk_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/README.md) instead.

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

Slurm example:

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-large
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /path/to/minimum_atomworks
source .venv/bin/activate

python -m minimum_atw.cli run-chunked \
  --config minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 100 \
  --workers 4
EOF
```

Slurm dry-run example:

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-large-dryrun
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /path/to/minimum_atomworks
source .venv/bin/activate

python -m minimum_atw.cli run-chunked \
  --config minimum_atw/examples/large_run/example_antibody_antigen_chunked.yaml \
  --chunk-size 10 \
  --workers 2
EOF
```
