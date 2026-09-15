#!/bin/bash

pip3 install numpy==2.1.3 pandas==2.2.3 scipy==1.14.1 networkx==3.4.2 -q

python3 /solution/solve_pipeline.py
cd /app && python3 run_analysis.py
