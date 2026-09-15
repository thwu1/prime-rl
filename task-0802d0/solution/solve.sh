#!/bin/bash

pip3 install numpy==1.26.4 scipy==1.13.1 -q

cd /app
python3 /solution/sdc_solver.py
