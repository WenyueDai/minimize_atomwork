from __future__ import annotations

import tempfile
from pathlib import Path

import biotite.structure as struc
from biotite.structure.io import load_structure, save_structure

from ..rosetta_common import (
    parse_score_jd2_scorefile,
    resolve_database,
    resolve_relax_executable,
    resolve_score_jd2_executable,
    run_relax,
    run_score_jd2,
)
from .base import BaseStructureManipulation


class RosettaPreprocessManipulation(BaseStructureManipulation):
    """Prepare-phase manipulation: score → repack/relax → score.

    Runs Rosetta scoring and optional sidechain repack / backbone relax on each
    structure, then writes the processed coordinates back to context.  Superimposition
    is NOT performed here — add ``superimpose_to_reference`` to the manipulations
    list (before or after this step) to handle alignment independently.

    When ``rosetta_preprocess: false`` in the config the Rosetta steps are skipped
    and the manipulation simply passes coordinates through unchanged.

    Params (under ``plugin_params.rosetta_preprocess``):
        repack   Sidechain-only fast optimisation (backbone fixed). Default: True.
        relax    Full fast-relax including backbone. Default: False.

    Config keys consumed at the root level:
        rosetta_preprocess           bool — master on/off switch (default True).
        rosetta_score_jd2_executable Path to score_jd2 binary (auto-discovered).
        rosetta_relax_executable     Path to relax binary (auto-discovered).
        rosetta_database             Path to Rosetta database (auto-discovered).
    """

    name = "rosetta_preprocess"
    prefix = "rosprep"

    def _params(self, ctx) -> dict:
        return dict(getattr(ctx.config, "plugin_params", {}).get(self.name, {}))

    def available(self, ctx) -> tuple[bool, str]:
        if ctx is None:
            return True, ""
        if not getattr(ctx.config, "rosetta_preprocess", True):
            # Rosetta steps disabled — manipulation is a no-op; always available.
            return True, ""
        score_jd2 = resolve_score_jd2_executable(ctx.config)
        if not score_jd2:
            return False, "Rosetta score_jd2 executable not found"
        database = resolve_database(score_jd2, ctx.config)
        if not database:
            return False, "Rosetta database not found"
        params = self._params(ctx)
        do_repack = params.get("repack", True)
        do_relax = params.get("relax", False)
        if do_repack or do_relax:
            relax_exe = resolve_relax_executable(ctx.config)
            if not relax_exe:
                return False, "Rosetta relax executable not found (needed for repack/relax)"
        return True, ""

    def run(self, ctx):
        params = self._params(ctx)
        do_rosetta = getattr(ctx.config, "rosetta_preprocess", True)
        pre_scores: dict = {}
        post_scores: dict = {}
        mobile: struc.AtomArray = ctx.aa.copy()

        if do_rosetta:
            score_jd2 = resolve_score_jd2_executable(ctx.config)
            database = resolve_database(score_jd2, ctx.config) if score_jd2 else None
            if not score_jd2 or not database:
                print(f"[WARN] rosetta_preprocess: Rosetta executables not found for {ctx.path}; skipping Rosetta steps")
            else:
                do_repack = params.get("repack", True)
                do_relax = params.get("relax", False)
                relax_exe = resolve_relax_executable(ctx.config) if (do_repack or do_relax) else None

                try:
                    with tempfile.TemporaryDirectory(prefix="minimum_atw_rosprep_") as tmp_dir:
                        tmp = Path(tmp_dir)
                        input_pdb = tmp / "input.pdb"
                        save_structure(input_pdb, mobile)

                        # ── 1. Pre-score ────────────────────────────────────
                        pre_sc = tmp / "pre.sc"
                        run_score_jd2(
                            executable=score_jd2,
                            database=database,
                            input_path=input_pdb,
                            score_path=pre_sc,
                        )
                        pre_scores = parse_score_jd2_scorefile(pre_sc)

                        # ── 2. Repack / relax ───────────────────────────────
                        processed_pdb = input_pdb
                        if (do_repack or do_relax) and relax_exe:
                            relax_out = tmp / "relax_out"
                            relax_out.mkdir()
                            processed_pdb = run_relax(
                                executable=relax_exe,
                                database=database,
                                input_path=input_pdb,
                                output_dir=relax_out,
                                backbone_move=bool(do_relax),
                            )

                        # ── 3. Post-score ───────────────────────────────────
                        post_sc = tmp / "post.sc"
                        run_score_jd2(
                            executable=score_jd2,
                            database=database,
                            input_path=processed_pdb,
                            score_path=post_sc,
                        )
                        post_scores = parse_score_jd2_scorefile(post_sc)

                        # ── 4. Load processed structure ─────────────────────
                        mobile = load_structure(processed_pdb)

                except Exception as exc:
                    import subprocess as _sp
                    if isinstance(exc, _sp.CalledProcessError):
                        err = exc.stderr.strip() or exc.stdout.strip() or type(exc).__name__
                    else:
                        err = str(exc) or type(exc).__name__
                    print(
                        f"[WARN] rosetta_preprocess: Rosetta step failed for {ctx.path}: {err.splitlines()[-1]}"
                    )

        ctx.aa = mobile
        ctx.rebuild_views()

        yield {
            "grain": "structure",
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "rosetta_steps_applied": do_rosetta and bool(pre_scores),
            **{f"pre_{k}": v for k, v in pre_scores.items()},
            **{f"post_{k}": v for k, v in post_scores.items()},
        }
