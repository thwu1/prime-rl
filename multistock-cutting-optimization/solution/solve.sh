#!/bin/bash

pip3 install PuLP==2.9.0 -q

cd /app
python3 /solution/solver.py
