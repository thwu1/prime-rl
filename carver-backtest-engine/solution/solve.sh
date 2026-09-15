#!/bin/bash

pip3 install numpy==2.1.3 pandas==2.2.3 pyyaml==6.0.2 -q

python3 /solution/fix_bugs.py

cd /app
python3 /app/run_backtest.py
