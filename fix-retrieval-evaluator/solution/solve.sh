#!/bin/bash

pip3 install numpy==2.1.3 pytrec-eval-terrier==0.5.6 -q

cd /app
python3 /solution/solver.py
