#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cd /app
python3 /solution/calibrate.py
