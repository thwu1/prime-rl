#!/bin/bash

pip3 install kociemba==1.2.1 cffi==1.17.1 -q
cp /solution/solver.py /app/pipeline.py
python3 /app/pipeline.py
