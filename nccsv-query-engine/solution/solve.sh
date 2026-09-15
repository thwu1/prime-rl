#!/bin/bash

pip3 install numpy==1.26.4 netCDF4==1.7.1 -q

cd /app
python3 /solution/convert_profiles.py
