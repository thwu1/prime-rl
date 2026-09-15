#!/bin/bash

# numpy and pyyaml are already installed via apt (python3-numpy, python3-yaml)

# Deploy fixed eval_tool.py
cp /solution/rec_eval_fixed.py /app/eval_tool.py

# Deploy fixed score_converter.py
cp /solution/score_converter_fixed.py /app/score_converter.py

# Convert score-matrix scenarios
mkdir -p /app/processed/scenario4 /app/processed/scenario5
python3 /app/score_converter.py /app/data/scenario4 /app/processed/scenario4
python3 /app/score_converter.py /app/data/scenario5 /app/processed/scenario5

# Smoke test on all scenarios
mkdir -p /app/results
python3 /app/eval_tool.py /app/data/scenario1 /app/results/scenario1.json
python3 /app/eval_tool.py /app/data/scenario2 /app/results/scenario2.json
python3 /app/eval_tool.py /app/data/scenario3 /app/results/scenario3.json
python3 /app/eval_tool.py /app/processed/scenario4 /app/results/scenario4.json
python3 /app/eval_tool.py /app/processed/scenario5 /app/results/scenario5.json

echo "Solution deployed successfully."
