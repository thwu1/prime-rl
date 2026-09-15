#!/bin/bash

set -e

pip3 install numpy==2.1.3 matplotlib==3.9.2 -q

cp /solution/gum_mcm_solution.py /app/gum_mcm.py
cp /solution/run_analysis_solution.py /app/run_analysis.py

cd /app
python3 run_analysis.py
