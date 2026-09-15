#!/bin/bash

pip3 install cantera==3.1.0 numpy==2.1.3 -q

cd /app
python3 /solution/solve.py
