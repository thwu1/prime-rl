#!/usr/bin/env bash

set -e

pip3 install QuantLib==1.36 -q

cd /app
python3 /solution/hull_white_solver.py
