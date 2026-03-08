from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
from typing import Any

from ..core.config import Config
from .chunked import CHUNK_PLAN_NAME, plan_chunked_pipeline


SLURM_SCRIPT_DIRNAME = "slurm_scripts"
SLURM_LOG_DIRNAME = "slurm_logs"
SLURM_SUBMISSION_NAME = "slurm_submission.json"
SLURM_MANIFEST_NAME = "chunk_config_manifest.txt"


def _read_chunk_plan(plan_dir: Path) -> dict[str, Any]:
    plan_path = plan_dir / CHUNK_PLAN_NAME
    if not plan_path.exists():
        raise FileNotFoundError(f"Chunk plan not found: {plan_path}")
    return json.loads(plan_path.read_text())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _shell_quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def _array_spec(n_chunks: int, array_limit: int | None) -> str:
    if n_chunks < 1:
        raise ValueError("Slurm submission requires at least one chunk")
    spec = f"1-{int(n_chunks)}"
    if array_limit is not None:
        limit = int(array_limit)
        if limit < 1:
            raise ValueError("array_limit must be at least 1")
        spec = f"{spec}%{limit}"
    return spec


def _write_chunk_manifest(plan_dir: Path, plan: dict[str, Any]) -> Path:
    manifest_path = plan_dir / SLURM_MANIFEST_NAME
    config_paths = [
        str(Path(item["chunk_config_path"]).resolve())
        for item in list(plan.get("chunks") or [])
    ]
    manifest_path.write_text("".join(f"{path}\n" for path in config_paths))
    return manifest_path


def _script_dir(plan_dir: Path) -> Path:
    target = plan_dir / SLURM_SCRIPT_DIRNAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def _log_dir(plan_dir: Path, log_dir: str | Path | None) -> Path:
    target = Path(log_dir).resolve() if log_dir is not None else (plan_dir / SLURM_LOG_DIRNAME).resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def _write_script(script_dir: Path, name: str, body: str) -> Path:
    path = script_dir / name
    path.write_text(body)
    path.chmod(0o755)
    return path


def _array_script_body(
    *,
    workdir: Path,
    manifest_path: Path,
    command: str,
) -> str:
    return (
        "#!/bin/bash\n"
        "set -euo pipefail\n\n"
        f"cd {_shell_quote(workdir)}\n"
        f'CONFIG=$(sed -n "${{SLURM_ARRAY_TASK_ID}}p" {_shell_quote(manifest_path)})\n'
        f"{command}\n"
    )


def _single_script_body(
    *,
    workdir: Path,
    command: str,
) -> str:
    return (
        "#!/bin/bash\n"
        "set -euo pipefail\n\n"
        f"cd {_shell_quote(workdir)}\n"
        f"{command}\n"
    )


def _build_prepare_command(python_bin: Path) -> str:
    return f"{_shell_quote(python_bin)} -m minimum_atw.cli prepare --config \"$CONFIG\""


def _build_run_plugins_command(python_bin: Path, plugins: list[str]) -> str:
    plugin_args = " ".join(shlex.quote(str(name)) for name in plugins)
    return (
        f"{_shell_quote(python_bin)} -m minimum_atw.cli run-plugins "
        f"--config \"$CONFIG\" --plugins {plugin_args}"
    )


def _build_merge_command(python_bin: Path) -> str:
    return f"{_shell_quote(python_bin)} -m minimum_atw.cli merge --config \"$CONFIG\""


def _build_analyze_command(python_bin: Path) -> str:
    return f"{_shell_quote(python_bin)} -m minimum_atw.cli analyze-dataset --config \"$CONFIG\""


def _build_merge_planned_command(
    python_bin: Path,
    *,
    plan_dir: Path,
    out_dir: str | Path | None,
) -> str:
    command = (
        f"{_shell_quote(python_bin)} -m minimum_atw.cli merge-planned-chunks "
        f"--plan-dir {_shell_quote(plan_dir)}"
    )
    if out_dir is not None:
        command += f" --out-dir {_shell_quote(Path(out_dir).resolve())}"
    return command


def _submit_job(
    *,
    label: str,
    script_path: Path,
    sbatch_args: list[str],
    dry_run: bool,
    depends_on_labels: list[str],
) -> dict[str, Any]:
    record = {
        "label": label,
        "script_path": str(script_path),
        "sbatch_args": list(sbatch_args),
        "depends_on_labels": list(depends_on_labels),
        "submitted": False,
        "job_id": None,
    }
    if dry_run:
        return record

    result = subprocess.run(
        ["sbatch", "--parsable", *sbatch_args, str(script_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    job_id = result.stdout.strip().split(";", 1)[0].strip()
    if not job_id:
        raise RuntimeError(f"sbatch did not return a job id for {label}")
    record["submitted"] = True
    record["job_id"] = job_id
    return record


def _dependency_arg(job_ids: list[str]) -> str | None:
    resolved = [str(job_id).strip() for job_id in job_ids if str(job_id).strip()]
    if not resolved:
        return None
    return f"--dependency=afterok:{':'.join(resolved)}"


def _array_sbatch_args(
    *,
    job_name: str,
    array_spec: str,
    cpu_threads: int,
    gpu_devices: int,
    log_dir: Path,
    dependency: str | None,
    common_args: list[str],
    extra_args: list[str],
) -> list[str]:
    args = [
        f"--job-name={job_name}",
        f"--array={array_spec}",
        f"--cpus-per-task={max(1, int(cpu_threads))}",
        f"--output={log_dir / (job_name + '-%A_%a.out')}",
    ]
    if gpu_devices > 0:
        args.append(f"--gres=gpu:{int(gpu_devices)}")
    if dependency:
        args.append(dependency)
    args.extend(common_args)
    args.extend(extra_args)
    return args


def _single_sbatch_args(
    *,
    job_name: str,
    cpu_threads: int,
    gpu_devices: int,
    log_dir: Path,
    dependency: str | None,
    common_args: list[str],
    extra_args: list[str],
) -> list[str]:
    args = [
        f"--job-name={job_name}",
        f"--cpus-per-task={max(1, int(cpu_threads))}",
        f"--output={log_dir / (job_name + '-%j.out')}",
    ]
    if gpu_devices > 0:
        args.append(f"--gres=gpu:{int(gpu_devices)}")
    if dependency:
        args.append(dependency)
    args.extend(common_args)
    args.extend(extra_args)
    return args


def _resolved_mode(requested_mode: str, submission_plan: dict[str, Any]) -> str:
    normalized = str(requested_mode or "auto").strip().lower()
    if normalized not in {"auto", "mixed", "staged"}:
        raise ValueError(f"Unsupported Slurm submission mode: {requested_mode}")
    if normalized != "auto":
        return normalized
    recommended = str(submission_plan.get("recommended_mode") or "single_job").strip().lower()
    if recommended == "split_by_stage":
        return "staged"
    return "mixed"


def submit_slurm_plan(
    plan_dir: str | Path,
    *,
    workdir: str | Path,
    python_bin: str | Path,
    mode: str = "auto",
    out_dir: str | Path | None = None,
    dry_run: bool = False,
    array_limit: int | None = None,
    log_dir: str | Path | None = None,
    sbatch_common_args: list[str] | None = None,
    sbatch_mixed_args: list[str] | None = None,
    sbatch_cpu_args: list[str] | None = None,
    sbatch_gpu_args: list[str] | None = None,
    sbatch_merge_args: list[str] | None = None,
) -> dict[str, Any]:
    resolved_plan_dir = Path(plan_dir).resolve()
    plan = _read_chunk_plan(resolved_plan_dir)
    chunks = list(plan.get("chunks") or [])
    if not chunks:
        raise ValueError(f"Chunk plan contains no chunks: {resolved_plan_dir / CHUNK_PLAN_NAME}")

    source_cfg = Config(**dict(plan["source_config"]))
    resource_plan = dict(plan.get("resource_plan") or {})
    submission_plan = dict(resource_plan.get("submission_plan") or {})
    resolved_mode = _resolved_mode(mode, submission_plan)

    resolved_workdir = Path(workdir).resolve()
    resolved_python = Path(python_bin).resolve()
    manifest_path = _write_chunk_manifest(resolved_plan_dir, plan)
    script_dir = _script_dir(resolved_plan_dir)
    resolved_log_dir = _log_dir(resolved_plan_dir, log_dir)
    array_spec = _array_spec(len(chunks), array_limit)

    common_args = list(sbatch_common_args or [])
    mixed_args = list(sbatch_mixed_args or [])
    cpu_args = list(sbatch_cpu_args or [])
    gpu_args = list(sbatch_gpu_args or [])
    merge_args = list(sbatch_merge_args or [])

    cpu_job_args = list(cpu_args)
    submission_jobs: list[dict[str, Any]] = []
    job_ids_by_label: dict[str, str] = {}

    def _record_job(
        *,
        label: str,
        script_name: str,
        body: str,
        sbatch_args: list[str],
        depends_on_labels: list[str],
    ) -> dict[str, Any]:
        script_path = _write_script(script_dir, script_name, body)
        record = _submit_job(
            label=label,
            script_path=script_path,
            sbatch_args=sbatch_args,
            dry_run=dry_run,
            depends_on_labels=depends_on_labels,
        )
        submission_jobs.append(record)
        if record["job_id"] is not None:
            job_ids_by_label[label] = str(record["job_id"])
        return record

    if resolved_mode == "mixed":
        mixed_request = dict(resource_plan.get("recommended_chunk_job") or {})
        mixed_cpu = max(1, int(mixed_request.get("cpu_threads") or 1))
        mixed_gpu = max(0, int(mixed_request.get("gpu_devices") or 0))
        mixed_body = _array_script_body(
            workdir=resolved_workdir,
            manifest_path=manifest_path,
            command=f"{_shell_quote(resolved_python)} -m minimum_atw.cli run --config \"$CONFIG\"",
        )
        mixed_record = _record_job(
            label="mixed_chunks",
            script_name="10_mixed_chunks.sh",
            body=mixed_body,
            sbatch_args=_array_sbatch_args(
                job_name="minatw-mixed",
                array_spec=array_spec,
                cpu_threads=mixed_cpu,
                gpu_devices=mixed_gpu,
                log_dir=resolved_log_dir,
                dependency=None,
                common_args=common_args,
                extra_args=mixed_args,
            ),
            depends_on_labels=[],
        )
        merge_dependency = _dependency_arg([job_ids_by_label.get("mixed_chunks", "")])
        final_merge_cpu = max(1, int(getattr(source_cfg, "cpu_workers", 1)))
        final_merge_body = _single_script_body(
            workdir=resolved_workdir,
            command=_build_merge_planned_command(resolved_python, plan_dir=resolved_plan_dir, out_dir=out_dir),
        )
        _record_job(
            label="merge_planned_chunks",
            script_name="99_merge_planned_chunks.sh",
            body=final_merge_body,
            sbatch_args=_single_sbatch_args(
                job_name="minatw-merge-final",
                cpu_threads=final_merge_cpu,
                gpu_devices=0,
                log_dir=resolved_log_dir,
                dependency=merge_dependency,
                common_args=common_args,
                extra_args=merge_args,
            ),
            depends_on_labels=["mixed_chunks"] if mixed_record else [],
        )
    else:
        prepare_record = _record_job(
            label="prepare_chunks",
            script_name="00_prepare_chunks.sh",
            body=_array_script_body(
                workdir=resolved_workdir,
                manifest_path=manifest_path,
                command=_build_prepare_command(resolved_python),
            ),
            sbatch_args=_array_sbatch_args(
                job_name="minatw-prepare",
                array_spec=array_spec,
                cpu_threads=max(1, int(getattr(source_cfg, "cpu_workers", 1))),
                gpu_devices=0,
                log_dir=resolved_log_dir,
                dependency=None,
                common_args=common_args,
                extra_args=cpu_job_args,
            ),
            depends_on_labels=[],
        )
        prior_labels = ["prepare_chunks"] if prepare_record else []

        for stage in list(submission_plan.get("stages") or []):
            stage_labels: list[str] = []
            prior_job_ids = [job_ids_by_label.get(label, "") for label in prior_labels]
            dependency = _dependency_arg(prior_job_ids)
            stage_index = int(stage.get("stage") or 0)
            for job in list(stage.get("jobs") or []):
                worker_pool = str(job.get("worker_pool") or "cpu").strip().lower()
                label = f"stage{stage_index}_{worker_pool}"
                job_request = dict(job.get("recommended_chunk_job") or {})
                cpu_threads = max(1, int(job_request.get("cpu_threads") or 1))
                gpu_devices = max(0, int(job_request.get("gpu_devices") or 0))
                plugins = [str(name) for name in list(job.get("plugins") or [])]
                if not plugins:
                    continue
                body = _array_script_body(
                    workdir=resolved_workdir,
                    manifest_path=manifest_path,
                    command=_build_run_plugins_command(resolved_python, plugins),
                )
                extra_args = gpu_args if worker_pool == "gpu" else cpu_job_args
                _record_job(
                    label=label,
                    script_name=f"{10 + stage_index:02d}_stage{stage_index}_{worker_pool}.sh",
                    body=body,
                    sbatch_args=_array_sbatch_args(
                        job_name=f"minatw-stage{stage_index}-{worker_pool}",
                        array_spec=array_spec,
                        cpu_threads=cpu_threads,
                        gpu_devices=gpu_devices,
                        log_dir=resolved_log_dir,
                        dependency=dependency,
                        common_args=common_args,
                        extra_args=extra_args,
                    ),
                    depends_on_labels=list(prior_labels),
                )
                stage_labels.append(label)
            if stage_labels:
                prior_labels = stage_labels

        merge_chunk_dependency = _dependency_arg([job_ids_by_label.get(label, "") for label in prior_labels])
        merge_chunk_record = _record_job(
            label="merge_chunks",
            script_name="90_merge_chunks.sh",
            body=_array_script_body(
                workdir=resolved_workdir,
                manifest_path=manifest_path,
                command=_build_merge_command(resolved_python),
            ),
            sbatch_args=_array_sbatch_args(
                job_name="minatw-merge-chunk",
                array_spec=array_spec,
                cpu_threads=max(1, int(getattr(source_cfg, "cpu_workers", 1))),
                gpu_devices=0,
                log_dir=resolved_log_dir,
                dependency=merge_chunk_dependency,
                common_args=common_args,
                extra_args=cpu_job_args,
            ),
            depends_on_labels=list(prior_labels),
        )
        prior_labels = ["merge_chunks"] if merge_chunk_record else prior_labels

        if source_cfg.chunk_dataset_analyses():
            chunk_analyze_dependency = _dependency_arg([job_ids_by_label.get(label, "") for label in prior_labels])
            analyze_record = _record_job(
                label="analyze_chunks",
                script_name="95_analyze_chunks.sh",
                body=_array_script_body(
                    workdir=resolved_workdir,
                    manifest_path=manifest_path,
                    command=_build_analyze_command(resolved_python),
                ),
                sbatch_args=_array_sbatch_args(
                    job_name="minatw-analyze-chunk",
                    array_spec=array_spec,
                    cpu_threads=max(1, int(getattr(source_cfg, "cpu_workers", 1))),
                    gpu_devices=0,
                    log_dir=resolved_log_dir,
                    dependency=chunk_analyze_dependency,
                    common_args=common_args,
                    extra_args=cpu_job_args,
                ),
                depends_on_labels=list(prior_labels),
            )
            prior_labels = ["analyze_chunks"] if analyze_record else prior_labels

        final_merge_dependency = _dependency_arg([job_ids_by_label.get(label, "") for label in prior_labels])
        _record_job(
            label="merge_planned_chunks",
            script_name="99_merge_planned_chunks.sh",
            body=_single_script_body(
                workdir=resolved_workdir,
                command=_build_merge_planned_command(resolved_python, plan_dir=resolved_plan_dir, out_dir=out_dir),
            ),
            sbatch_args=_single_sbatch_args(
                job_name="minatw-merge-final",
                cpu_threads=max(1, int(getattr(source_cfg, "cpu_workers", 1))),
                gpu_devices=0,
                log_dir=resolved_log_dir,
                dependency=final_merge_dependency,
                common_args=common_args,
                extra_args=merge_args,
            ),
            depends_on_labels=list(prior_labels),
        )

    submission = {
        "plan_dir": str(resolved_plan_dir),
        "plan_path": str((resolved_plan_dir / CHUNK_PLAN_NAME).resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "script_dir": str(script_dir.resolve()),
        "log_dir": str(resolved_log_dir.resolve()),
        "mode_requested": str(mode),
        "mode_submitted": resolved_mode,
        "dry_run": bool(dry_run),
        "n_chunks": len(chunks),
        "jobs": submission_jobs,
    }
    _write_json(resolved_plan_dir / SLURM_SUBMISSION_NAME, submission)
    return submission


def submit_slurm_chunked_pipeline(
    cfg: Config | None,
    *,
    chunk_size: int | None,
    plan_dir: str | Path,
    reuse_plan: bool = False,
    workdir: str | Path,
    python_bin: str | Path,
    mode: str = "auto",
    out_dir: str | Path | None = None,
    dry_run: bool = False,
    array_limit: int | None = None,
    log_dir: str | Path | None = None,
    sbatch_common_args: list[str] | None = None,
    sbatch_mixed_args: list[str] | None = None,
    sbatch_cpu_args: list[str] | None = None,
    sbatch_gpu_args: list[str] | None = None,
    sbatch_merge_args: list[str] | None = None,
) -> dict[str, Any]:
    resolved_plan_dir = Path(plan_dir).resolve()
    if reuse_plan:
        if not (resolved_plan_dir / CHUNK_PLAN_NAME).exists():
            raise FileNotFoundError(f"Chunk plan not found: {resolved_plan_dir / CHUNK_PLAN_NAME}")
    else:
        if cfg is None:
            raise ValueError("cfg is required unless reuse_plan=True")
        if chunk_size is None:
            raise ValueError("chunk_size is required unless reuse_plan=True")
        plan_chunked_pipeline(cfg, chunk_size=int(chunk_size), plan_dir=resolved_plan_dir)

    return submit_slurm_plan(
        resolved_plan_dir,
        workdir=workdir,
        python_bin=python_bin,
        mode=mode,
        out_dir=out_dir,
        dry_run=dry_run,
        array_limit=array_limit,
        log_dir=log_dir,
        sbatch_common_args=sbatch_common_args,
        sbatch_mixed_args=sbatch_mixed_args,
        sbatch_cpu_args=sbatch_cpu_args,
        sbatch_gpu_args=sbatch_gpu_args,
        sbatch_merge_args=sbatch_merge_args,
    )
