#!/bin/bash
export PIP_BREAK_SYSTEM_PACKAGES=1
pip3 install numpy==2.1.3 -q
cp /solution/estimator.py /app/estimator.py
python3 /app/estimator.py /app/data /app/output/estimated_trajectory.csv
