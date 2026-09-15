#!/usr/bin/env bash

pip3 install numpy==2.1.3 netCDF4==1.7.2 -q 2>/dev/null

python3 /solution/cmorize.py
