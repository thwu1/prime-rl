#!/bin/bash

pip3 install numpy==2.1.3 -q

python3 /solution/fix_pipeline.py

cd /app && python3 -m pipeline.main
