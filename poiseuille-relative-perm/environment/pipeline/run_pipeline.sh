#!/bin/bash
# Single-phase Poiseuille flow pipeline
# Orchestrates: gmsh (mesh) -> read_mesh.py (parse) -> solver.m (solve) -> postprocess.py
#
# Usage: ./run_pipeline.sh [N] [mu] [G] [H] [work_dir]

set -e

N=${1:-100}
MU=${2:-1.0}
G_VAL=${3:-1.0}
H_VAL=${4:-1.0}
WORK_DIR=${5:-/tmp/pipeline_work}

mkdir -p "$WORK_DIR"

echo "=== Mesh generation (gmsh, N=$N) ==="
gmsh -1 /app/pipeline/mesh.geo -setnumber N "$N" -o "$WORK_DIR/mesh.msh" -format msh2 2>/dev/null

echo "=== Extracting node coordinates ==="
python3 /app/pipeline/read_mesh.py "$WORK_DIR/mesh.msh" > "$WORK_DIR/nodes.txt"

echo "=== Solving (Octave, mu=$MU, G=$G_VAL) ==="
octave --no-gui --silent /app/pipeline/solver.m "$WORK_DIR/nodes.txt" "$MU" "$G_VAL" "$WORK_DIR/velocity.dat"

echo "=== Post-processing ==="
python3 /app/pipeline/postprocess.py "$WORK_DIR/velocity.dat" "$H_VAL"

echo "=== Pipeline complete ==="
