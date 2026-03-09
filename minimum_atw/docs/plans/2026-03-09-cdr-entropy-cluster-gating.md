# CDR Entropy And Cluster Gating Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make dataset CDR entropy output position-wise and require explicit `cluster.mode` before clustering runs.

**Architecture:** Keep the change local to dataset analysis plugins. Reuse existing antibody-numbered CDR strings for aligned CDR positions, keep full-sequence diversity as a simple sequence-level summary, and make cluster opt-in by tightening parameter normalization.

**Tech Stack:** Python, pandas, unittest

---

### Task 1: Define the new entropy behavior with tests

**Files:**
- Modify: `tests/test_cdr_entropy.py`
- Test: `tests/test_dataset_analysis_runtime.py`

**Step 1: Write the failing tests**

- Add a unit test asserting `cdr1` emits position rows with per-position entropy and a summary row.
- Add a unit test asserting `sequence` still emits only a sequence-level summary row.
- Add a runtime-level test asserting the persisted dataset output contains the new row types.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cdr_entropy.py tests/test_dataset_analysis_runtime.py -q`

**Step 3: Write minimal implementation**

- Update `plugins/dataset/calculation/cdr_entropy.py` to emit summary and position rows for CDRs.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cdr_entropy.py tests/test_dataset_analysis_runtime.py -q`

### Task 2: Require explicit cluster mode

**Files:**
- Modify: `tests/test_dataset_cluster.py`
- Modify: `plugins/dataset/calculation/cluster.py`

**Step 1: Write the failing test**

- Add a cluster test asserting no cluster columns are written when `distance_threshold` is provided without `mode`.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_dataset_cluster.py -q`

**Step 3: Write minimal implementation**

- Change cluster parameter handling so mode is required to enable clustering.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_dataset_cluster.py -q`

### Task 3: Verify the complete change set

**Files:**
- Modify: `plugins/dataset/calculation/cdr_entropy.py`
- Modify: `plugins/dataset/calculation/cluster.py`
- Modify: `tests/test_cdr_entropy.py`
- Modify: `tests/test_dataset_analysis_runtime.py`
- Modify: `tests/test_dataset_cluster.py`

**Step 1: Run focused verification**

Run: `pytest tests/test_cdr_entropy.py tests/test_dataset_analysis_runtime.py tests/test_dataset_cluster.py -q`

**Step 2: Review diff**

Run: `git diff -- plugins/dataset/calculation/cdr_entropy.py plugins/dataset/calculation/cluster.py tests/test_cdr_entropy.py tests/test_dataset_analysis_runtime.py tests/test_dataset_cluster.py docs/plans/2026-03-09-cdr-entropy-cluster-gating-design.md docs/plans/2026-03-09-cdr-entropy-cluster-gating.md`

**Step 3: Commit**

Optional, only if requested by the user.
