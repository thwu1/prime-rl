#!/bin/bash

pip3 install python-sat==1.8.dev13 -q

cd /app
python3 /solution/solver.py
