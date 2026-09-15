#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 h5py==3.11.0 -q

cp /solution/solve.py /app/wec_analysis.py
cd /app
python3 /app/wec_analysis.py full
