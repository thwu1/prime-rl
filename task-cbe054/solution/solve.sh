#!/bin/bash

pip3 install jsonschema==4.23.0 -q

cp /solution/solver.py /app/run_pipeline.py
cd /app
python3 /app/run_pipeline.py
