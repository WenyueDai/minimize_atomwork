# Chunk Run Examples

This folder is for manual chunk configs: one config per chunk, one output directory per chunk, and optional scheduler control outside the package.

Current example policy:

- chunk YAMLs enable all non-Rosetta features that are useful for local chunk testing
- Rosetta is scaffolded but commented out

## Files

- [chunk_antibody_antigen_01.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml)
- [chunk_antibody_antigen_02.yaml](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml)
- [chunk_config_manifest_example.txt](/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_config_manifest_example.txt)

## Run the chunk examples

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_01.yaml

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run \
  --config /home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_antibody_antigen_02.yaml
```

## Merge the finished chunk outputs

```bash
/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge-datasets \
  --out-dir /home/eva/minimum_atomworks/out_antibody_antigen_merged \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_01 \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_02
```

## What the chunk YAMLs show

- both built-in manipulations
- all non-Rosetta antibody/interface plugins
- dataset-level analyses
- checkpoint and prepared-cache toggles as commented options
- a full Rosetta block ready to uncomment later

## Enabling Rosetta later

When you want Rosetta in chunk runs, uncomment the plugin and Rosetta block in the chunk YAMLs. The scaffold already includes:

- `score_jd2` preprocessing
- native `-fixedchains` target selection
- packed vs no-pack controls
- packstat controls

```bash
MANIFEST=/home/eva/minimum_atomworks/minimum_atw/examples/chunk_run/chunk_config_manifest_example.txt
```

Generic pattern:

```bash
sbatch --array=1-3 <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%A_%a.out
set -euo pipefail

cd /home/eva/minimum_atomworks

MANIFEST=/home/eva/minimum_atomworks/path/to/chunk_config_manifest.txt
CONFIG=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$MANIFEST")

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli run --config "$CONFIG"
EOF
```

This is the safest pattern when chunk config names are arbitrary.

### Merge job

```bash
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=minimum-atw-chunk-merge
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

cd /home/eva/minimum_atomworks

/home/eva/miniconda3/envs/atw_pp/bin/python -m minimum_atw.cli merge-datasets \
  --out-dir /home/eva/minimum_atomworks/out_antibody_antigen_merged \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_01 \
  --source-out-dir /home/eva/minimum_atomworks/out_chunk_antibody_antigen_02
EOF
```

## Notes

- These manual chunk examples keep `numbering_roles` and `interface_contacts` enabled, so merged `interfaces.parquet` can contain antibody CDR interface columns.
- Chunk outputs must still be compatible before merge. Different numbering setup or different final table columns are expected to fail the merge.
- If you want automatically generated scheduler-ready chunk configs from one large config, use `plan-chunks` in [large_run/README.md](/home/eva/minimum_atomworks/minimum_atw/examples/large_run/README.md).
