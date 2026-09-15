#!/bin/bash


pip3 install numpy==2.1.3 -q

python3 /solution/fix_pipeline.py

cd /app && make all
