#!/usr/bin/env bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cd /app
python3 /solution/solve_helper.py
