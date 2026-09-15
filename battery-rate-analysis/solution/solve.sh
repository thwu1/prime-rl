#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/analyze_fixed.py /app/analyze.py
python3 /app/analyze.py
