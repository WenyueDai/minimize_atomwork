from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


def _normalize_columns(df: pd.DataFrame) -> dict[str, str]:
    return {str(col).strip().lower(): str(col) for col in df.columns}


def _pick_column(columns: dict[str, str], *patterns: str) -> str | None:
    for pattern in patterns:
        for lowered, original in columns.items():
            if pattern in lowered:
                return original
    return None


def _load_output_metrics(out_dir: Path) -> dict[str, float]:
    output_csv = out_dir / "output.csv"
    if not output_csv.exists():
        return {}

    df = pd.read_csv(output_csv)
    if df.empty:
        return {}

    row = df.iloc[0]
    cols = _normalize_columns(df)
    score_col = _pick_column(cols, "abepiscore", "abepi_score")
    target_col = _pick_column(cols, "abepitarget", "abepi_target")

    metrics: dict[str, float] = {}
    if score_col is not None:
        try:
            metrics["score"] = float(row[score_col])
        except Exception:
            pass
    if target_col is not None:
        try:
            metrics["target_score"] = float(row[target_col])
        except Exception:
            pass
    return metrics


class AbEpiTopeRuntime:
    def __init__(self) -> None:
        import biotite.structure as struc
        import torch

        if not hasattr(struc, "filter_backbone") and hasattr(struc, "filter_peptide_backbone"):
            struc.filter_backbone = struc.filter_peptide_backbone

        from abepitope.main import EvalAbAgs, StructureData

        self._torch = torch
        self._original_torch_load = torch.load
        self._EvalAbAgs = EvalAbAgs
        self._StructureData = StructureData

        def compat_torch_load(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return self._original_torch_load(*args, **kwargs)

        self._torch.load = compat_torch_load

    def close(self) -> None:
        self._torch.load = self._original_torch_load

    def run(self, structure_path: Path, *, atom_radius: float = 4.0) -> dict[str, float]:
        captured_stdout = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout):
            with tempfile.TemporaryDirectory(prefix="minimum_atw_abepitope_") as tmp_dir:
                base = Path(tmp_dir)
                enc_dir = base / "encodings"
                tmp_work_dir = base / "temporary"
                out_dir = base / "output"
                enc_dir.mkdir(parents=True, exist_ok=True)
                tmp_work_dir.mkdir(parents=True, exist_ok=True)
                out_dir.mkdir(parents=True, exist_ok=True)

                data = self._StructureData()
                data.encode_proteins(structure_path, enc_dir, tmp_work_dir, atom_radius=atom_radius)
                eval_abags = self._EvalAbAgs(data)
                eval_abags.predict(out_dir)
                return _load_output_metrics(out_dir)


def run_abepitope(structure_path: Path, *, atom_radius: float = 4.0) -> dict[str, float]:
    runtime = AbEpiTopeRuntime()
    try:
        return runtime.run(structure_path, atom_radius=atom_radius)
    finally:
        runtime.close()


def _worker_loop() -> int:
    runtime = AbEpiTopeRuntime()
    try:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                print(json.dumps({"ok": False, "error": f"JSONDecodeError: {exc}"}), flush=True)
                continue

            if request.get("cmd") == "shutdown":
                print(json.dumps({"ok": True}), flush=True)
                return 0

            try:
                structure_path = Path(str(request["structure_path"])).resolve()
                atom_radius = float(request.get("atom_radius", 4.0))
                metrics = runtime.run(structure_path, atom_radius=atom_radius)
                print(json.dumps({"ok": True, "metrics": metrics}), flush=True)
            except Exception as exc:
                print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), flush=True)
        return 0
    finally:
        runtime.close()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--worker":
        return _worker_loop()

    if not argv:
        print("Usage: abepitope_runner.py [--worker] <structure_path> [atom_radius]", file=sys.stderr)
        return 2

    structure_path = Path(argv[0]).resolve()
    atom_radius = float(argv[1]) if len(argv) > 1 else 4.0
    metrics = run_abepitope(structure_path, atom_radius=atom_radius)
    print(json.dumps(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
