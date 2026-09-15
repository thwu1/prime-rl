#!/bin/bash

pip3 install mpmath==1.3.0 scipy==1.14.1 numpy==2.1.3 --no-cache-dir -q 2>&1
python3 /solution/solve_helpers.py
