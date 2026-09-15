#!/bin/bash

pip3 install numpy==2.1.3 pandas==2.2.3 h5py==3.11.0 -q

cd /app
python3 /solution/solve_pwater.py
