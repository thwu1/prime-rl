#!/usr/bin/env bash

pip3 install scikit-learn==1.5.2 scipy==1.14.1 -q
cp /solution/solution.py /app/analyze.py
cd /app && python3 analyze.py
