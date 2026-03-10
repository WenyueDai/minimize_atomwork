#!/usr/bin/env bash
# make_rosetta_singularity_wrappers.sh
#
# Generates three thin wrapper scripts that invoke Rosetta executables
# through Singularity.  Run this once on your HPC login node, then point
# your minimum-atomworks YAML at the generated wrapper paths.
#
# Usage:
#   bash scripts/make_rosetta_singularity_wrappers.sh [OPTIONS]
#
# Options:
#   --sif PATH        Path to the Rosetta SIF image
#                     (default: /apps/.images/rosetta/rosetta_2025.sif)
#   --bind PATHS      Extra --bind mounts, comma-separated
#                     (default: /scratch:/scratch)
#   --out-dir DIR     Directory to write the wrapper scripts
#                     (default: $HOME/bin)
#
# After running, add the output directory to your PATH and update your
# YAML config:
#
#   rosetta_executable:       ~/bin/InterfaceAnalyzer
#   rosetta_score_jd2_executable: ~/bin/score_jd2
#   rosetta_relax_executable: ~/bin/relax

set -euo pipefail

SIF="/apps/.images/rosetta/rosetta_2025.sif"
BIND="/scratch:/scratch"
OUT_DIR="$HOME/bin"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sif)    SIF="$2";     shift 2 ;;
        --bind)   BIND="$2";    shift 2 ;;
        --out-dir) OUT_DIR="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

mkdir -p "$OUT_DIR"

# Map of wrapper-name -> Rosetta executable name inside the container.
# Rosetta ships multiple build variants; list them in preference order.
declare -A TOOLS=(
    [InterfaceAnalyzer]="InterfaceAnalyzer.static.linuxgccrelease InterfaceAnalyzer.linuxgccrelease InterfaceAnalyzer.default.linuxgccrelease"
    [score_jd2]="score_jd2.static.linuxgccrelease score_jd2.linuxgccrelease score_jd2.default.linuxgccrelease"
    [relax]="relax.static.linuxgccrelease relax.linuxgccrelease relax.default.linuxgccrelease"
)

for WRAPPER_NAME in "${!TOOLS[@]}"; do
    WRAPPER="$OUT_DIR/$WRAPPER_NAME"
    CANDIDATES="${TOOLS[$WRAPPER_NAME]}"

    cat > "$WRAPPER" <<SCRIPT
#!/usr/bin/env bash
# Auto-generated Singularity wrapper for Rosetta $WRAPPER_NAME
# SIF: $SIF
set -euo pipefail

SIF="$SIF"
BIND="$BIND"

# Try each build variant in order until one exists inside the container.
for EXE in $CANDIDATES; do
    if singularity exec --bind "\$BIND" "\$SIF" test -x "/usr/local/bin/\$EXE" 2>/dev/null || \\
       singularity exec --bind "\$BIND" "\$SIF" which "\$EXE" >/dev/null 2>&1; then
        exec singularity exec --bind "\$BIND" "\$SIF" "\$EXE" "\$@"
    fi
done

# Fallback: let Singularity sort it out (will error if truly absent)
exec singularity exec --bind "\$BIND" "\$SIF" $WRAPPER_NAME "\$@"
SCRIPT

    chmod +x "$WRAPPER"
    echo "Created: $WRAPPER"
done

echo ""
echo "Done.  Add the following to your minimum-atomworks YAML:"
echo ""
echo "  rosetta_executable:           $OUT_DIR/InterfaceAnalyzer"
echo "  rosetta_score_jd2_executable: $OUT_DIR/score_jd2"
echo "  rosetta_relax_executable:     $OUT_DIR/relax"
echo ""
echo "Also set your Rosetta database path, e.g.:"
echo "  rosetta_database: /scratch/scratch01/wd591631/Rosetta_database/rosetta/database"
