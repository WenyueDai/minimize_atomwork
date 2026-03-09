# CDR Entropy And Cluster Gating Design

## Goal

Make `cdr_entropy` more meaningful by reporting position-wise diversity for aligned CDRs, and stop `cluster` from running unless the user explicitly selects a clustering mode.

## Scope

- Replace the current whole-string CDR entropy summary with position-wise output for `cdr1`, `cdr2`, and `cdr3`.
- Keep `sequence` handling simple and meaningful by reporting sequence-level diversity summaries only.
- Require explicit `cluster.mode` before clustering is enabled.

## Design

### CDR entropy

The current plugin treats each CDR string as one token, so datasets where every sequence is unique collapse to the same entropy value. For antibody CDRs this is not very informative.

The revised plugin will use the already-numbered antibody CDR strings from `abseq__cdr*_sequence` and compute per-position amino-acid entropy across rows of the same role. This avoids introducing a new alignment dependency because the existing antibody numbering step already defines aligned CDR regions.

For each role and CDR region, the plugin will emit:

- one summary row with aggregate diversity fields
- one row per position with residue counts and Shannon entropy

For `sequence`, the plugin will stay sequence-level only. Full-length sequence position-wise entropy would require an explicit alignment policy and would add complexity that does not fit the current minimal design.

### Cluster gating

Clustering should only run when the user explicitly opts in with `cluster.mode`. If `cluster` appears in `dataset_analyses` but `dataset_analysis_params.cluster.mode` is missing or blank, the plugin should return no rows and not modify `pdb.parquet`.

Once enabled, existing defaults stay intact:

- `absolute_interface_ca` and `shape_interface_ca` remain the valid modes
- if `interface_side` is omitted, clustering still runs both left and right jobs

## Testing

- Add tests for position-wise `cdr_entropy` output shape and values.
- Add tests confirming `sequence` remains sequence-level.
- Add tests confirming `cluster` is skipped when `mode` is not explicitly set.
