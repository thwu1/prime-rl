#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cp /solution/scoring_rules.py /app/scoring_rules.py
cp /solution/evaluate.py /app/evaluate.py

# Ensure scenario data is available
mkdir -p /app/data
cp /solution/scenarios.json /app/data/scenarios.json

cd /app
python3 evaluate.py
