#!/bin/bash

set -e

pip3 install pyyaml==6.0.2 -q

cp /solution/analyzer.py /app/run_optimizer.py

cd /app
python3 run_optimizer.py
make visualize
