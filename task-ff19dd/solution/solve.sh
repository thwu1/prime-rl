#!/bin/bash

pip3 install tsplib95==0.7.1 ortools==9.9.3963 -q
cd /app
python3 /solution/solver.py
