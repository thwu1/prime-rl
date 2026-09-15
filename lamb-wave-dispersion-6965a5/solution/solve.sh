#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 pyyaml==6.0.2 -q

cd /app
cp /solution/solver.py /app/dispersion.py

python3 /app/dispersion.py /app/configs/aluminum_1mm.yaml -o /app/output/aluminum.json
python3 /app/dispersion.py /app/configs/composite_0_90_2s.yaml -o /app/output/composite.json
