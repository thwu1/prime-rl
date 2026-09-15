#!/bin/bash

pip3 install numpy==2.1.3 requests==2.32.3 -q
cd /app
python3 /solution/solve_trajectory.py
