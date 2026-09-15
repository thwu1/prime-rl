#!/bin/bash

pip3 install numpy==2.1.3 h5py==3.12.1 -q

cd /app
python3 /solution/smc_abc_solution.py
