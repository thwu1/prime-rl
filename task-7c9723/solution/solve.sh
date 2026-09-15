#!/bin/bash

pip3 install pulp==2.9.0 -q

cd /app
python3 /solution/solver.py
