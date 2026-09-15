#!/usr/bin/env bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q
python3 /solution/fix_solver.py
python3 /solution/evaluate.py
