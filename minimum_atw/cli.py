from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from .core.config import Config
from .core.extensions import EXTENSION_CLASSES, extension_catalog, extension_catalog_by_category
from .core.pipeline import (
    merge_dataset_outputs,
    merge_outputs,
    prepare_outputs,
    run_chunked_pipeline,
    run_pipeline,
    run_plugin,
)
from .plugins.dataset_analysis.runtime import analyze_dataset_outputs


def _load_config(config_path: str) -> Config:
    data = yaml.safe_load(Path(config_path).read_text())
    return Config(**data)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("minimum_atomworks")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Prepare, run all configured plugins, then merge outputs")
    run_parser.add_argument("--config", required=True, help="Path to YAML config")

    run_chunked_parser = subparsers.add_parser("run-chunked", help="Split one input_dir into chunks, run them in parallel, then merge final outputs")
    run_chunked_parser.add_argument("--config", required=True, help="Path to YAML config")
    run_chunked_parser.add_argument("--chunk-size", required=True, type=int, help="Maximum number of structures per chunk")
    run_chunked_parser.add_argument("--workers", type=int, default=1, help="Number of chunk workers to run in parallel")

    prepare_parser = subparsers.add_parser("prepare", help="Apply manipulations once, cache prepared structures, and write base tables")
    prepare_parser.add_argument("--config", required=True, help="Path to YAML config")

    plugin_parser = subparsers.add_parser("run-plugin", help="Run one plugin against prepared structures")
    plugin_parser.add_argument("--config", required=True, help="Path to YAML config")
    plugin_parser.add_argument("--plugin", required=True, help="Plugin name to run")

    merge_parser = subparsers.add_parser("merge", help="Merge prepared tables with plugin outputs")
    merge_parser.add_argument("--config", required=True, help="Path to YAML config")

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


def _print_extension_catalog() -> None:
    catalog = extension_catalog()
    for class_name, spec in EXTENSION_CLASSES.items():
        print(spec.display_name)
        print(f"  config key: {spec.config_key}")
        print(f"  stage: {spec.stage}")
        print(f"  description: {spec.description}")
        for item in catalog.get(class_name, []):
            line = f"  - {item.name} category={item.analysis_category}"
            if item.execution != "n/a":
                line += f" execution={item.execution}"
            print(line)
    print("Analysis Categories")
    by_category = extension_catalog_by_category()
    for category, items in by_category.items():
        print(f"  {category}")
        for item in items:
            print(f"    - {item.name} ({item.extension_class})")


def main() -> None:
    parser = _build_parser()
    argv = sys.argv[1:]
    if not argv or argv[0].startswith("-"):
        argv = ["run", *argv]

    args = parser.parse_args(argv)

    if args.command == "list-extensions":
        _print_extension_catalog()
        return

    if args.command == "prepare":
        cfg = _load_config(args.config)
        counts = prepare_outputs(cfg)
        _print_counts("Prepare complete", counts)
        return

    if args.command == "run-chunked":
        cfg = _load_config(args.config)
        counts = run_chunked_pipeline(cfg, chunk_size=args.chunk_size, workers=args.workers)
        _print_counts("Chunked run complete", counts)
        return

    if args.command == "run-plugin":
        cfg = _load_config(args.config)
        counts = run_plugin(cfg, args.plugin)
        _print_counts(f"Plugin run complete: {args.plugin}", counts)
        return

    if args.command == "merge":
        cfg = _load_config(args.config)
        counts = merge_outputs(cfg)
        _print_counts("Merge complete", counts)
        return

    if args.command == "merge-datasets":
        counts = merge_dataset_outputs(args.source_out_dirs, args.out_dir)
        _print_counts("Dataset merge complete", counts)
        print(f"  merged_from: {', '.join(args.source_out_dirs)}")
        print(f"  merged_to: {args.out_dir}")
        return

    if args.command == "analyze-dataset":
        cfg = _load_config(args.config)
        summary = analyze_dataset_outputs(
            Path(cfg.out_dir).resolve(),
            dataset_analyses=tuple(cfg.dataset_analyses) or None,
            dataset_analysis_params=cfg.dataset_analysis_params,
            dataset_annotations=cfg.dataset_annotations,
        )
        print("Dataset analysis complete")
        for key, value in summary.items():
            print(f"  {key}: {value}")
        return

    cfg = _load_config(args.config)
    counts = run_pipeline(cfg)
    _print_counts("Run complete", counts)


if __name__ == "__main__":
    main()
