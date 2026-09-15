#!/bin/bash

pip3 install pytest==8.3.4 -q

# If results missing, attempt recompile + rerun as best effort
if [ ! -f /app/results.csv ]; then
    if [ -f /app/robertson_ext.c ]; then
        cd /app && R CMD SHLIB robertson_ext.c 2>/dev/null || true
    fi
    if [ -f /app/run_solver.R ]; then
        cd /app && Rscript run_solver.R 2>/dev/null || true
    fi
fi

cd /app

pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
