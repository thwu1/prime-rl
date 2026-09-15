#!/bin/bash

cp /solution/simulator.py /app/simulator.py
cp /solution/run_sim.py /app/run_simulation.py

cd /app
python3 /app/run_simulation.py
