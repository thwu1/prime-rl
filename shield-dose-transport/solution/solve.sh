#!/bin/bash

pip3 install h5py==3.12.1 numpy==2.1.3 -q

cd /app
python3 /solution/solver.py
