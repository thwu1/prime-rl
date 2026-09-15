#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 pandas==2.2.3 statsmodels==0.14.4 -q

cp /solution/solve_pipeline.py /app/count_pipeline.py
cd /app && python3 count_pipeline.py
