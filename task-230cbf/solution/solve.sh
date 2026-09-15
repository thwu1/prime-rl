#!/bin/bash


cd /app

# Verify data files are present
for f in data/experiment.csv data/grid_spec.csv \
         data/submission_fun3d_sa.dat data/submission_overflow_sst.csv \
         data/submission_su2_sa.fwf data/submission_tau_rsm.jsonl \
         data/submission_cfl3d_sa.tsv; do
    if [ ! -f "$f" ]; then
        echo "ERROR: Missing data file: /app/$f"
        exit 1
    fi
done

python3 /solution/solver.py
