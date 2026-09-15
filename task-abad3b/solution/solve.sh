#!/bin/bash

cd /app

python3 -m pip install pandas==2.2.3 scipy==1.14.1 numpy==2.1.3 -q 2>&1

python3 /solution/analysis.py
