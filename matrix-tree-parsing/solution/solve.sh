#!/bin/bash

pip3 install numpy==2.1.3 -q

python3 /solution/write_solution.py

cd /app
python3 /app/pipeline.py
