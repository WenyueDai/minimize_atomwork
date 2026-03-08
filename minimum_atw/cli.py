from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from .core.config import Config
from .core.extensions import EXTENSION_CLASSES, extension_catalog
from .core.pipeline import (
    merge_planned_chunks,
    merge_dataset_outputs,
    merge_outputs,
    plan_chunked_pipeline,
    prepare_outputs,
    run_chunked_pipeline,
    run_pipeline,
    run_plugin,
    run_plugins,
    submit_slurm_chunked_pipeline,
)
from .plugins.dataset.calculation.runtime import analyze_dataset_outputs


def _load_config(config_path: str) -> Config:
    data = yaml.safe_load(Path(config_path).read_text())
    return Config(**data)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("minimum_atomworks")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Prepare, run all configured plugins, then merge outputs")
    run_parser.add_argument("--config", required=True, help="Path to YAML config")
    run_parser.add_argument("--checkpoint-enabled", dest="checkpoint_enabled", action="store_true",
                            help="Enable checkpointing (overrides config file)")

    run_chunked_parser = subparsers.add_parser("run-chunked", help="Split one input_dir into chunks, run them in parallel, then merge final outputs")
    run_chunked_parser.add_argument("--config", required=True, help="Path to YAML config")
    run_chunked_parser.add_argument("--chunk-size", required=True, type=int, help="Maximum number of structures per chunk")
    run_chunked_parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Maximum chunk workers to run in parallel; the runtime may reduce this to respect chunk CPU/GPU budgets",
    )

    plan_chunks_parser = subparsers.add_parser("plan-chunks", help="Create deterministic chunk configs and inputs for scheduler-driven chunk execution")
    plan_chunks_parser.add_argument("--config", required=True, help="Path to YAML config")
    plan_chunks_parser.add_argument("--chunk-size", required=True, type=int, help="Maximum number of structures per chunk")
    plan_chunks_parser.add_argument("--plan-dir", required=True, help="Output directory for the generated chunk plan")

    merge_planned_parser = subparsers.add_parser("merge-planned-chunks", help="Merge outputs from a previously generated chunk plan")
    merge_planned_parser.add_argument("--plan-dir", required=True, help="Directory created by plan-chunks")
    merge_planned_parser.add_argument("--out-dir", help="Optional override for merged final output directory")

    submit_slurm_parser = subparsers.add_parser(
        "submit-slurm",
        help="Plan chunked work if needed, then submit mixed or staged chunk jobs to Slurm",
    )
    submit_slurm_parser.add_argument("--plan-dir", help="Chunk plan directory to create or reuse; defaults to slurm.plan_dir or <out_dir>_plan")
    submit_slurm_parser.add_argument("--config", help="Path to YAML config; required unless --reuse-plan is set")
    submit_slurm_parser.add_argument("--chunk-size", type=int, help="Maximum number of structures per chunk; defaults to slurm.chunk_size")
    submit_slurm_parser.add_argument("--reuse-plan", action="store_true", help="Reuse an existing chunk_plan.json instead of replanning")
    submit_slurm_parser.add_argument("--mode", choices=("auto", "mixed", "staged"),
                                     help="Submission style override; defaults to slurm.mode or auto")
    submit_slurm_parser.add_argument("--out-dir", help="Optional override for merged final output directory")
    submit_slurm_parser.add_argument("--dry-run", action="store_true", help="Write scripts and submission metadata without calling sbatch")
    submit_slurm_parser.add_argument("--array-limit", type=int, help="Optional Slurm array concurrency limit (N in 1-M%%N); defaults to slurm.array_limit")
    submit_slurm_parser.add_argument("--workdir", help="Working directory override for generated Slurm scripts")
    submit_slurm_parser.add_argument("--python-bin", help="Python interpreter override for submitted jobs")
    submit_slurm_parser.add_argument("--log-dir", help="Optional directory override for Slurm stdout/stderr logs")
    submit_slurm_parser.add_argument("--sbatch-common-arg", action="append",
                                     help="Extra sbatch argument applied to every submitted job; repeat as needed")
    submit_slurm_parser.add_argument("--sbatch-mixed-arg", action="append",
                                     help="Extra sbatch argument applied to mixed chunk jobs; repeat as needed")
    submit_slurm_parser.add_argument("--sbatch-cpu-arg", action="append",
                                     help="Extra sbatch argument applied to CPU-only array jobs; repeat as needed")
    submit_slurm_parser.add_argument("--sbatch-gpu-arg", action="append",
                                     help="Extra sbatch argument applied to GPU-enabled array jobs; repeat as needed")
    submit_slurm_parser.add_argument("--sbatch-merge-arg", action="append",
                                     help="Extra sbatch argument applied to the final merge job; repeat as needed")

    prepare_parser = subparsers.add_parser("prepare", help="Apply manipulations once, cache prepared structures, and write base tables")
    prepare_parser.add_argument("--config", required=True, help="Path to YAML config")
    prepare_parser.add_argument("--checkpoint-enabled", dest="checkpoint_enabled", action="store_true",
                                help="Enable checkpointing (overrides config file)")

    plugin_parser = subparsers.add_parser("run-plugin", help="Run one plugin against prepared structures")
    plugin_parser.add_argument("--config", required=True, help="Path to YAML config")
    plugin_parser.add_argument("--plugin", required=True, help="Plugin name to run")
    plugin_parser.add_argument("--checkpoint-enabled", dest="checkpoint_enabled", action="store_true",
                                help="Enable checkpointing (overrides config file)")

    plugins_parser = subparsers.add_parser("run-plugins", help="Run multiple plugins against prepared structures (incremental development workflow)")
    plugins_parser.add_argument("--config", required=True, help="Path to YAML config")
    plugins_parser.add_argument("--plugins", required=True, nargs="+", help="Plugin names to run (space separated)")
    plugins_parser.add_argument("--checkpoint-enabled", dest="checkpoint_enabled", action="store_true",
                                help="Enable checkpointing (overrides config file)")

    merge_parser = subparsers.add_parser("merge", help="Merge prepared tables with plugin outputs")
    merge_parser.add_argument("--config", required=True, help="Path to YAML config")
    merge_parser.add_argument("--checkpoint-enabled", dest="checkpoint_enabled", action="store_true",
                              help="Enable checkpointing (only affects run-plugin/prepare runs when invoked later)")

    merge_datasets_parser = subparsers.add_parser("merge-datasets", help="Merge multiple completed out_dirs into one final dataset")
    merge_datasets_parser.add_argument("--out-dir", required=True, help="Output directory for the merged dataset")
    merge_datasets_parser.add_argument(
        "--source-out-dir",
        dest="source_out_dirs",
        action="append",
        required=True,
        help="Completed out_dir to merge; repeat for multiple chunk outputs",
    )

    dataset_parser = subparsers.add_parser("analyze-dataset", help="Run dataset-level analysis on final outputs")
    dataset_parser.add_argument("--config", required=True, help="Path to YAML config")
    subparsers.add_parser("list-extensions", help="List extension classes and registered extensions")

    return parser


def _print_counts(label: str, counts: dict[str, int]) -> None:
    print(label)
    for key, value in counts.items():
        print(f"  {key}: {value}")


def _print_submission_summary(label: str, submission: dict[str, object]) -> None:
    print(label)
    print(f"  plan_dir: {submission['plan_dir']}")
    print(f"  manifest_path: {submission['manifest_path']}")
    print(f"  mode_requested: {submission['mode_requested']}")
    print(f"  mode_submitted: {submission['mode_submitted']}")
    print(f"  dry_run: {submission['dry_run']}")
    print(f"  n_chunks: {submission['n_chunks']}")
    print("  jobs:")
    for job in list(submission.get("jobs") or []):
        status = f"job_id={job['job_id']}" if job.get("job_id") else "job_id=dry-run"
        depends = ",".join(job.get("depends_on_labels") or []) or "-"
        print(f"    {job['label']}: {status} depends_on={depends}")


def main() -> None:
    parser = _build_parser()
    argv = sys.argv[1:]
    if not argv or argv[0].startswith("-"):
        argv = ["run", *argv]

    args = parser.parse_args(argv)

    if args.command == "prepare":
        cfg = _load_config(args.config)
        if getattr(args, "checkpoint_enabled", False):
            cfg = cfg.model_copy(update={"checkpoint_enabled": True})
        counts = prepare_outputs(cfg)
        _print_counts("Prepare complete", counts)
        return

    if args.command == "run-chunked":
        cfg = _load_config(args.config)
        counts = run_chunked_pipeline(cfg, chunk_size=args.chunk_size, workers=args.workers)
        _print_counts("Chunked run complete", counts)
        return

    if args.command == "plan-chunks":
        cfg = _load_config(args.config)
        counts = plan_chunked_pipeline(cfg, chunk_size=args.chunk_size, plan_dir=args.plan_dir)
        _print_counts("Chunk plan complete", counts)
        print(f"  plan_dir: {args.plan_dir}")
        return

    if args.command == "merge-planned-chunks":
        counts = merge_planned_chunks(args.plan_dir, out_dir=args.out_dir)
        _print_counts("Planned chunk merge complete", counts)
        print(f"  plan_dir: {args.plan_dir}")
        if args.out_dir:
            print(f"  merged_to: {args.out_dir}")
        return

    if args.command == "submit-slurm":
        if not args.reuse_plan and not args.config:
            parser.error("--config is required unless --reuse-plan is set")
        if args.reuse_plan and not args.config and not args.plan_dir:
            parser.error("--plan-dir is required with --reuse-plan unless --config is also set")

        cfg = _load_config(args.config) if args.config else None
        submission = submit_slurm_chunked_pipeline(
            cfg,
            chunk_size=args.chunk_size,
            plan_dir=args.plan_dir,
            reuse_plan=bool(args.reuse_plan),
            workdir=args.workdir,
            python_bin=args.python_bin,
            mode=args.mode,
            out_dir=args.out_dir,
            dry_run=bool(args.dry_run),
            array_limit=args.array_limit,
            log_dir=args.log_dir,
            sbatch_common_args=list(args.sbatch_common_arg) if args.sbatch_common_arg is not None else None,
            sbatch_mixed_args=list(args.sbatch_mixed_arg) if args.sbatch_mixed_arg is not None else None,
            sbatch_cpu_args=list(args.sbatch_cpu_arg) if args.sbatch_cpu_arg is not None else None,
            sbatch_gpu_args=list(args.sbatch_gpu_arg) if args.sbatch_gpu_arg is not None else None,
            sbatch_merge_args=list(args.sbatch_merge_arg) if args.sbatch_merge_arg is not None else None,
        )
        _print_submission_summary("Slurm submission complete", submission)
        return

    if args.command == "run-plugin":
        cfg = _load_config(args.config)
        if getattr(args, "checkpoint_enabled", False):
            cfg = cfg.model_copy(update={"checkpoint_enabled": True})
        counts = run_plugin(cfg, args.plugin)
        _print_counts(f"Plugin run complete: {args.plugin}", counts)
        return

    if args.command == "run-plugins":
        cfg = _load_config(args.config)
        if getattr(args, "checkpoint_enabled", False):
            cfg = cfg.model_copy(update={"checkpoint_enabled": True})
        counts = run_plugins(cfg, args.plugins)
        _print_counts(f"Plugins run complete: {', '.join(args.plugins)}", counts)
        return

    if args.command == "merge":
        cfg = _load_config(args.config)
        if getattr(args, "checkpoint_enabled", False):
            cfg = cfg.model_copy(update={"checkpoint_enabled": True})
        counts = merge_outputs(cfg)
        _print_counts("Merge complete", counts)
        return

    if args.command == "merge-datasets":
        counts = merge_dataset_outputs(args.source_out_dirs, args.out_dir)
        _print_counts("Dataset merge complete", counts)
        print(f"  merged_from: {', '.join(args.source_out_dirs)}")
        print(f"  merged_to: {args.out_dir}")
        return

    if args.command == "list-extensions":
        catalog = extension_catalog()
        for extension_class, items in catalog.items():
            spec = EXTENSION_CLASSES[extension_class]
            print(f"{spec.display_name} ({extension_class})")
            for item in items:
                print(f"  {item.name}: stage={item.stage}, config={item.config_key or 'n/a'}")
        return

    if args.command == "analyze-dataset":
        cfg = _load_config(args.config)
        summary = analyze_dataset_outputs(
            Path(cfg.out_dir).resolve(),
            dataset_analyses=tuple(cfg.dataset_analyses) or None,
            dataset_analysis_params=cfg.dataset_analysis_params,
            dataset_annotations=cfg.dataset_annotations,
            reference_dataset_dir=cfg.reference_dataset_dir,
            cleanup_prepared_after_dataset_analysis=cfg.cleanup_prepared_after_dataset_analysis,
        )
        print("Dataset analysis complete")
        for key, value in summary.items():
            print(f"  {key}: {value}")
        return

    cfg = _load_config(args.config)
    if getattr(args, "checkpoint_enabled", False):
        cfg = cfg.model_copy(update={"checkpoint_enabled": True})
    counts = run_pipeline(cfg)
    _print_counts("Run complete", counts)


if __name__ == "__main__":
    main()
