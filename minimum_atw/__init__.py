from __future__ import annotations

__all__ = [
    "prepare_outputs",
    "run_plugin",
    "merge_outputs",
    "merge_dataset_outputs",
    "plan_chunked_pipeline",
    "merge_planned_chunks",
    "run_chunked_pipeline",
    "run_pipeline",
    "analyze_dataset_outputs",
]


def __getattr__(name: str):
    if name in {
        "prepare_outputs",
        "run_plugin",
        "merge_outputs",
        "merge_dataset_outputs",
        "plan_chunked_pipeline",
        "merge_planned_chunks",
        "run_chunked_pipeline",
        "run_pipeline",
    }:
        from .core.pipeline import (
            merge_planned_chunks,
            merge_dataset_outputs,
            merge_outputs,
            plan_chunked_pipeline,
            prepare_outputs,
            run_chunked_pipeline,
            run_pipeline,
            run_plugin,
        )

        namespace = {
            "prepare_outputs": prepare_outputs,
            "run_plugin": run_plugin,
            "merge_outputs": merge_outputs,
            "merge_dataset_outputs": merge_dataset_outputs,
            "plan_chunked_pipeline": plan_chunked_pipeline,
            "merge_planned_chunks": merge_planned_chunks,
            "run_chunked_pipeline": run_chunked_pipeline,
            "run_pipeline": run_pipeline,
        }
        return namespace[name]
    if name == "analyze_dataset_outputs":
        from .plugins.dataset_analysis.runtime import analyze_dataset_outputs

        return analyze_dataset_outputs
    raise AttributeError(name)
