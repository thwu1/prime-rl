#!/bin/bash

pip3 install numpy==1.26.4 scipy==1.13.1 -q
cp /solution/pce_solver.py /app/uq_pipeline.py
python3 /app/uq_pipeline.py
