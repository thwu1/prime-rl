#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cp /solution/nfiq2_solution.py /app/nfiq2_features.py
cd /app
python3 /app/nfiq2_features.py
