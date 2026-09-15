#!/bin/bash

pip3 install pyelftools==0.31 -q

cp /solution/analyzer.py /app/analyze.py
cd /app
python3 /app/analyze.py
