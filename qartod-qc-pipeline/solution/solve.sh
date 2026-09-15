#!/bin/bash

pip3 install numpy==2.1.3 pandas==2.2.3 pyyaml==6.0.2 -q

cp /solution/qc_engine.py /app/qc_engine.py
cp /solution/run_qc.py /app/run_qc.py

python3 /app/run_qc.py
