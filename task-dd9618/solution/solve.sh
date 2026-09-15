#!/bin/bash

pip3 install numpy==1.26.4 scikit-learn==1.5.2 scipy==1.13.1 -q

cp /solution/metrics_impl.py /app/metrics.py
cp /solution/smc_impl.py /app/smc_abc.py

cd /app
python3 /solution/solver.py
