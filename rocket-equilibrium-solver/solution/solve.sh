#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cp /solution/solver.py /app/rocket_eq.py
cd /app
python3 rocket_eq.py
