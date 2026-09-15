#!/bin/bash


pip3 install numpy==2.1.3 lxml==5.1.0 xacro==2.1.1 pyyaml==6.0.2 -q

cd /app
python3 /solution/solver.py
