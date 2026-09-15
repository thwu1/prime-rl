#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Ensure input files are available in /app/
if [ ! -f /app/survey.csv ]; then
    cp /opt/taskdata/survey.csv /app/survey.csv 2>/dev/null || true
fi
if [ ! -f /app/prediction_grid.csv ]; then
    cp /opt/taskdata/prediction_grid.csv /app/prediction_grid.csv 2>/dev/null || true
fi

cp /solution/solver.py /app/eqs_pipeline.py
python3 /app/eqs_pipeline.py /app/survey.csv /app/prediction_grid.csv /app/predictions.csv /app/diagnostics.json
