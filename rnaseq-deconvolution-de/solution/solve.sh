#!/bin/bash

pip3 install scipy==1.14.1 statsmodels==0.14.4 numpy==2.1.3 pandas==2.2.3 -q

cd /app
python3 /solution/solve_helper.py
