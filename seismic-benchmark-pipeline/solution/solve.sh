#!/bin/bash

cd /app

pip3 install numpy==2.1.3 -q
pip3 install h5py==3.12.1 scipy==1.14.1 scikit-learn==1.5.2 -q

python3 /solution/solver.py
