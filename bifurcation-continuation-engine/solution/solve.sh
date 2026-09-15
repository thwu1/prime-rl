#!/bin/bash


pip3 install numpy==2.1.3 scipy==1.14.1 -q

cp /solution/solver.py /app/analyze.py
cd /app
python3 /app/analyze.py
