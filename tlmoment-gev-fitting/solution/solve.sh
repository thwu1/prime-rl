#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cp /solution/solver.py /app/analysis.py
cd /app
python3 /app/analysis.py
