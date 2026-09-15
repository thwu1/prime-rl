#!/usr/bin/env bash

pip3 install pytest==8.3.4 -q

export FOAM_SIGFPE=false

# Source OpenFOAM environment
. /usr/lib/openfoam/openfoam2312/etc/bashrc 2>/dev/null || true

# Run analyze.py if it exists — this produces the convergence report
if [ -f /app/analyze.py ]; then
    cd /app/cavity
    rm -rf constant/polyMesh processor* [1-9]* [1-9]*.[0-9]* log.* postProcessing
    cd /app
    python3 /app/analyze.py 2>&1 || echo "analyze.py exited with code $?"
fi

# Run the base case fresh to verify the fixes independently
cd /app/cavity
rm -rf constant/polyMesh processor* [1-9]* [1-9]*.[0-9]* log.* postProcessing

blockMesh > log.blockMesh 2>&1
BLOCKMESH_EXIT=$?

if [ $BLOCKMESH_EXIT -eq 0 ]; then
    simpleFoam > log.simpleFoam 2>&1
fi

# Run pytest
cd /
pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
