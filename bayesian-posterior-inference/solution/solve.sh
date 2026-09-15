#!/bin/bash


pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Copy solver to /app/ workspace so inference code is discoverable there
cp /solution/solver.py /app/solver.py

python3 /app/solver.py
