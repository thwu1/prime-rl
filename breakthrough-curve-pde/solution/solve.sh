#!/bin/bash

pip3 install numpy==1.26.4 scipy==1.13.1 -q

cp /solution/solve.py /app/analyze.py
cd /app && python3 analyze.py
