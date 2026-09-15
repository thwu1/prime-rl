#!/bin/bash

pip3 install numpy==2.1.3 -q

# Deploy complete implementations
cp /solution/microstructure.py /app/microstructure.py
cp /solution/run_simulation.py /app/run_simulation.py

cd /app
python3 run_simulation.py
