#!/bin/bash

pip3 install numpy==2.1.3 pyyaml==6.0.2 -q
cd /app
python3 /solution/evaluate_solution.py
