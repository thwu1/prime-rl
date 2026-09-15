#!/bin/bash

set -e
export PIP_BREAK_SYSTEM_PACKAGES=1

python3 -m pip install numpy==1.26.4 scipy==1.13.1 -q --no-cache-dir

cp /solution/szhw_pricer.py /app/szhw_pricer.py
cp /solution/calibrate_szhw.py /app/calibrate_szhw.py
cp /solution/generate_report.py /app/generate_report.py
cp /solution/Makefile /app/Makefile

cd /app
make calibrate
make report
