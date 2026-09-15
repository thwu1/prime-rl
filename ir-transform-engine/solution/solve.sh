#!/bin/bash

pip3 install pyyaml==6.0.2 -q

cp /solution/irtool_solution.py /app/irtool.py

cd /app
python3 /app/irtool.py
