#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cp /solution/astro_solution.py /app/astro.py
cp /solution/analyze_solution.py /app/analyze.py
cp /solution/filter_obs_solution.py /app/filter_obs.py
cp /solution/makefile_solution /app/Makefile

cd /app
make all
