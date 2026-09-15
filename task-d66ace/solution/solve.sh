#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/simulator.py /app/simulator.py
cp /solution/run_simulation.py /app/run_simulation.py

cd /app && python3 run_simulation.py
