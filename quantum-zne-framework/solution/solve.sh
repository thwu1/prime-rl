#!/bin/bash

pip3 install scipy==1.14.1 numpy==2.1.3 -q

cp /solution/noise_scaling.py /app/noise_scaling.py
cp /solution/extrapolation.py /app/extrapolation.py
cp /solution/run_benchmark.py /app/run_benchmark.py

cd /app
python3 run_benchmark.py
