#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q
mkdir -p /app/results
cp /solution/euler_pipeline.py /app/pipeline.py
cd /app && python3 pipeline.py
