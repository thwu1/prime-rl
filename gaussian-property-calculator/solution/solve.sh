#!/bin/bash

python3 -m pip install numpy==2.1.3 scipy==1.14.1 -q

cp /solution/solver.py /app/compute_properties.py
cd /app
python3 compute_properties.py
