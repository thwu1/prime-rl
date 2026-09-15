#!/bin/bash

pip3 install numpy==2.1.3 pydot==2.0.0 PyYAML==6.0.2 -q
python3 /solution/implement.py
cp /solution/run_pipeline.py /app/run_pipeline.py
python3 /app/run_pipeline.py
