#!/bin/bash

pip3 install numpy==1.26.4 pymoo==0.6.0 -q

cd /app

cp /solution/solver.py /app/hls_analyzer.py
python3 /app/hls_analyzer.py
