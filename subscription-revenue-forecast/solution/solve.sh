#!/bin/bash

pip3 install duckdb==1.1.3 tomli==2.0.1 -q

cd /app
python3 /solution/solver.py
