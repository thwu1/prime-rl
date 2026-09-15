#!/bin/bash

# Install solution dependencies
python3 -m pip install numpy==2.1.3 -q

cd /app
cp /solution/cosim_master.py /app/cosim_master.py
python3 /app/cosim_master.py
