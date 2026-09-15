#!/bin/bash

pip3 install numpy==1.26.4 scipy==1.13.1 -q

cp /solution/controller.py /app/controller.py

cd /app
python3 /app/run_simulation.py
