#!/bin/bash

set -e

pip3 install numpy==2.1.3 netCDF4==1.7.2 -q

python3 /solution/solve_pipeline.py
