#!/usr/bin/env bash

set -e

pip3 install numpy==2.1.3 scipy==1.14.1 pandas==2.2.3 -q

python3 /solution/solve_pipeline.py
