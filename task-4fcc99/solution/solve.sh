#!/bin/bash

pip3 install warp-lang==1.14.0 numpy==2.1.3 -q

cp /solution/pipeline_solution.py /app/pipeline.py

cd /app
python3 /app/pipeline.py
