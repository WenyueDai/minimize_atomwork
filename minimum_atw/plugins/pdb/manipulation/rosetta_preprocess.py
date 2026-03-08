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
from ..superimpose_common import load_reference_structure, superimpose_complex
from .base import BaseStructureManipulation


class RosettaPreprocessManipulation(BaseStructureManipulation):
    """Prepare-phase manipulation: score → repack/relax → score → superimpose.

    When ``rosetta_preprocess: false`` in the config the Rosetta scoring and
    repack/relax steps are skipped and the manipulation degrades gracefully to a
    plain superposition onto the reference (identical to
    ``superimpose_to_reference``).

    Params (under ``plugin_params.rosetta_preprocess``):
        reference_path   Path to the reference PDB for superimposition.
        on_chains        Chain IDs to use as the superimposition anchor.
        repack           Sidechain-only fast optimisation (backbone fixed).
                         Default: True.
        relax            Full fast-relax including backbone.  Default: False.

    Config keys consumed at the root level:
        rosetta_preprocess           bool — master on/off switch (default True).
        rosetta_score_jd2_executable Path to score_jd2 binary (auto-discovered).
        rosetta_relax_executable     Path to relax binary (auto-discovered).
        rosetta_database             Path to Rosetta database (auto-discovered).
    """

    name = "rosetta_preprocess"
    prefix = "rosprep"

    def __init__(self) -> None:
        self._reference: struc.AtomArray | None = None
        self._reference_path: str | None = None

    def _params(self, ctx) -> dict:
        return dict(getattr(ctx.config, "plugin_params", {}).get(self.name, {}))

    def available(self, ctx) -> tuple[bool, str]:
        if ctx is None:
            return True, ""
        if not getattr(ctx.config, "rosetta_preprocess", True):
            # Rosetta steps disabled — only superimpose; always available.
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
        ref_path = params.get("reference_path") or getattr(ctx.config, "superimpose_reference_path", None)
        on_chains_cfg = params.get("on_chains") or getattr(ctx.config, "superimpose_on_chains", [])
        on_chains = tuple(str(c) for c in on_chains_cfg if str(c))

        # ── Initialise reference ────────────────────────────────────────────
        if self._reference is None:
            if ref_path:
                self._reference_path = str(Path(ref_path).expanduser().resolve())
                self._reference = load_reference_structure(self._reference_path)
            else:
                self._reference = ctx.aa.copy()
                self._reference_path = ctx.path
                yield {
                    "grain": "structure",
                    "path": ctx.path,
                    "assembly_id": ctx.assembly_id,
                    "note": "reference_structure",
                }
                return

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

        # ── 5. Superimpose to reference ─────────────────────────────────────
        result = superimpose_complex(
            reference=self._reference,
            mobile=mobile,
            on_chains=on_chains,
        )
        ctx.aa = result.fitted_complex
        ctx.rebuild_views()

        shared_atoms_rmsd = float(
            struc.rmsd(self._reference[result.fixed_idx], result.fitted_complex[result.mobile_idx])
        )
        yield {
            "grain": "structure",
            "path": ctx.path,
            "assembly_id": ctx.assembly_id,
            "reference_path": self._reference_path,
            "on_chains": ";".join(on_chains),
            "anchor_atoms": int(len(result.fixed_anchor_idx)),
            "alignment_method": result.alignment_method,
            "shared_atoms_rmsd": shared_atoms_rmsd,
            "shared_atoms_count": int(len(result.fixed_idx)),
            "rosetta_steps_applied": do_rosetta and bool(pre_scores),
            **{f"pre_{k}": v for k, v in pre_scores.items()},
            **{f"post_{k}": v for k, v in post_scores.items()},
        }

        # Per-chain RMSD rows (same as superimpose_to_reference).
        fixed_chain = self._reference.chain_id[result.fixed_idx].astype(str)
        mobile_chain = result.fitted_complex.chain_id[result.mobile_idx].astype(str)
        for chain_id in sorted(set(fixed_chain) & set(mobile_chain)):
            chain_mask = (fixed_chain == chain_id) & (mobile_chain == chain_id)
            chain_fixed_idx = result.fixed_idx[chain_mask]
            chain_mobile_idx = result.mobile_idx[chain_mask]
            if len(chain_fixed_idx) == 0:
                continue
            chain_rmsd = float(struc.rmsd(
                self._reference[chain_fixed_idx],
                result.fitted_complex[chain_mobile_idx],
            ))
            yield {
                "grain": "chain",
                "path": ctx.path,
                "assembly_id": ctx.assembly_id,
                "chain_id": str(chain_id),
                "rmsd": chain_rmsd,
                "matched_atoms": int(len(chain_fixed_idx)),
            }
