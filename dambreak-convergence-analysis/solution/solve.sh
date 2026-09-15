#!/bin/bash

pip3 install numpy==1.26.4 -q

cp /solution/solver.py /app/dambreak_analysis.py
python3 /app/dambreak_analysis.py
