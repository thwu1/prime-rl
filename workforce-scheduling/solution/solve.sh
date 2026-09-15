#!/bin/bash

pip3 install ortools==9.11.4210 -q

cd /app
python3 /solution/solver.py
