#!/bin/bash

pip3 install scipy==1.14.1 numpy==2.1.3 -q

cd /app
python3 /solution/solver.py
