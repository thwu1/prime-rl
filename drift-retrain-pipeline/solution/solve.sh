#!/bin/bash

pip3 install scipy==1.14.1 pyyaml==6.0.2 -q

mkdir -p /app/pipeline
cp /solution/pipeline.py /app/pipeline/run_pipeline.py
python3 /app/pipeline/run_pipeline.py
