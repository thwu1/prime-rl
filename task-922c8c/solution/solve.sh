#!/usr/bin/env bash

pip3 install trimesh==4.5.3 scipy==1.14.1 pyyaml==6.0.2 numpy==2.1.3 networkx==3.4.2 -q

cp /solution/solver_impl.py /app/solver.py
chmod +x /app/solver.py

# Verify the solver works on the main scene
python3 /app/solver.py \
    --scene /app/scene.sdf \
    --constraints /app/constraints.yaml \
    --output-dir /tmp/solve_verify \
    --num-placements 10 \
    --seed 42
MAIN_EXIT=$?

if [ $MAIN_EXIT -ne 0 ]; then
    echo "Main scene verification failed: exit code $MAIN_EXIT"
    exit 1
fi
echo "Main scene verification: exit code $MAIN_EXIT"

# Verify it rejects the cyclic scene
python3 /app/solver.py \
    --scene /app/scene_cyclic.sdf \
    --constraints /app/constraints_cyclic.yaml \
    --output-dir /tmp/solve_cyclic \
    --seed 42 2>/dev/null
UNSAT_EXIT=$?
if [ $UNSAT_EXIT -eq 0 ]; then
    echo "ERROR: solver should have rejected cyclic scene"
    exit 1
fi

echo "Solution verified successfully."
