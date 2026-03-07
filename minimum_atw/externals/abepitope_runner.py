from __future__ import annotations

import contextlib
import io
import json
import math
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
            score = float(row[score_col])
            if math.isfinite(score):
                metrics["score"] = score
        except Exception:
            pass
    if target_col is not None:
        try:
            target_score = float(row[target_col])
            if math.isfinite(target_score):
                metrics["target_score"] = target_score
        except Exception:
            pass
    return metrics


class AbEpiTopeRuntime:
    def __init__(self) -> None:
        import biotite.structure as struc
        import torch

        if not hasattr(struc, "filter_backbone") and hasattr(struc, "filter_peptide_backbone"):
            struc.filter_backbone = struc.filter_peptide_backbone

        self._torch = torch
        self._original_torch_load = torch.load

        def compat_torch_load(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return self._original_torch_load(*args, **kwargs)

        self._torch.load = compat_torch_load

        import abepitope.main as _abepitope_main
        import abepitope.biopdb_utilities as _biopdb_utils
        from abepitope.main import EvalAbAgs, StructureData

        self._abepitope_main = _abepitope_main
        self._biopdb_utils = _biopdb_utils
        self._EvalAbAgs = EvalAbAgs
        self._StructureData = StructureData

        # Pre-load ESM-IF1 once and patch abepitope so encode_proteins reuses it.
        # Without this, encode_proteins reloads the 142M model from disk every call.
        _cached_esmif1 = _abepitope_main.ESMIF1Model()

        class _CachedESMIF1Model:
            def __new__(cls, *args, **kwargs):
                return _cached_esmif1

        _abepitope_main.ESMIF1Model = _CachedESMIF1Model

    def close(self) -> None:
        self._torch.load = self._original_torch_load

    def _patch_chain_identity(self, chain_hints: dict[str, list[str]] | None):
        if not chain_hints:
            return contextlib.nullcontext()

        heavy_chain_ids = {str(chain_id) for chain_id in chain_hints.get("heavy_chain_ids", []) if str(chain_id)}
        light_chain_ids = {str(chain_id) for chain_id in chain_hints.get("light_chain_ids", []) if str(chain_id)}
        antigen_chain_ids = {str(chain_id) for chain_id in chain_hints.get("antigen_chain_ids", []) if str(chain_id)}
        if (not heavy_chain_ids and not light_chain_ids) or not antigen_chain_ids:
            return contextlib.nullcontext()

        original = self._abepitope_main.identify_abag_with_hmm

        def _identify_with_hints(abag_path, hmm_models_directory, tmp, pdb_id="foo", hmm_eval=float(1e-18), verbose=True, abseq_type_lookup=None):
            if self._biopdb_utils.is_pdb_file(abag_path):
                model = self._biopdb_utils.read_pdb_structure(abag_path)
            elif self._biopdb_utils.is_cif_file(abag_path):
                model = self._biopdb_utils.read_cif_structure(abag_path)
            else:
                return original(
                    abag_path,
                    hmm_models_directory,
                    tmp,
                    pdb_id=pdb_id,
                    hmm_eval=hmm_eval,
                    verbose=verbose,
                    abseq_type_lookup=abseq_type_lookup,
                )

            chain_by_id = {chain.get_id(): chain for chain in model}
            heavy_chains = [chain_by_id[chain_id] for chain_id in sorted(heavy_chain_ids) if chain_id in chain_by_id]
            light_chains = [chain_by_id[chain_id] for chain_id in sorted(light_chain_ids) if chain_id in chain_by_id]
            antigen_chains = [chain_by_id[chain_id] for chain_id in sorted(antigen_chain_ids) if chain_id in chain_by_id]

            if (heavy_chains or light_chains) and antigen_chains:
                tmp.mkdir(parents=True, exist_ok=True)
                return heavy_chains, light_chains, antigen_chains
            return original(
                abag_path,
                hmm_models_directory,
                tmp,
                pdb_id=pdb_id,
                hmm_eval=hmm_eval,
                verbose=verbose,
                abseq_type_lookup=abseq_type_lookup,
            )

        @contextlib.contextmanager
        def _patched():
            self._abepitope_main.identify_abag_with_hmm = _identify_with_hints
            try:
                yield
            finally:
                self._abepitope_main.identify_abag_with_hmm = original

        return _patched()

    def _encode(self, structure_path: Path, enc_dir: Path, tmp_work_dir: Path, *, atom_radius: float):
        data = self._StructureData()
        data.encode_proteins(structure_path, enc_dir, tmp_work_dir, atom_radius=atom_radius)
        return data

    def run(
        self,
        pdb_content: str,
        *,
        seq_hash: str | None = None,
        atom_radius: float = 4.0,
        chain_hints: dict[str, list[str]] | None = None,
    ) -> dict[str, float]:
        captured_stdout = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout):
            with tempfile.TemporaryDirectory(prefix="minimum_atw_abepitope_") as tmp_dir:
                base = Path(tmp_dir)
                structure_path = base / "pair.pdb"
                structure_path.write_text(pdb_content)
                enc_dir = base / "encodings"
                tmp_work_dir = base / "temporary"
                out_dir = base / "output"
                enc_dir.mkdir(parents=True, exist_ok=True)
                tmp_work_dir.mkdir(parents=True, exist_ok=True)
                out_dir.mkdir(parents=True, exist_ok=True)

                with self._patch_chain_identity(chain_hints):
                    data = self._encode(structure_path, enc_dir, tmp_work_dir, atom_radius=atom_radius)
                    eval_abags = self._EvalAbAgs(data)
                    eval_abags.predict(out_dir)
                return _load_output_metrics(out_dir)


def run_abepitope(pdb_content: str, *, atom_radius: float = 4.0) -> dict[str, float]:
    runtime = AbEpiTopeRuntime()
    try:
        return runtime.run(pdb_content, atom_radius=atom_radius)
    finally:
        runtime.close()


def _worker_loop() -> int:
    runtime = AbEpiTopeRuntime()
    try:
        print(json.dumps({"ok": True, "event": "ready"}), flush=True)
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
                pdb_content = str(request["pdb_content"])
                seq_hash = request.get("seq_hash") or None
                atom_radius = float(request.get("atom_radius", 4.0))
                chain_hints = request.get("chain_hints")
                metrics = runtime.run(
                    pdb_content,
                    seq_hash=seq_hash,
                    atom_radius=atom_radius,
                    chain_hints=chain_hints if isinstance(chain_hints, dict) else None,
                )
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
    pdb_content = structure_path.read_text()
    metrics = run_abepitope(pdb_content, atom_radius=atom_radius)
    print(json.dumps(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
