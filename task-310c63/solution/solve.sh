#!/bin/bash

pip3 install numpy==1.26.4 -q

cp /solution/simulator.py /app/simulator.py
cp /solution/solve_main.py /app/solve.py

cd /app
python3 solve.py
