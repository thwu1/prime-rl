#!/bin/bash

pip3 install PuLP==2.9.0 -q

cp /solution/solver.py /app/solver.py
python3 /app/solver.py
