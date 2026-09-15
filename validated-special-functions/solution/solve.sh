#!/bin/bash

set -e
export PIP_BREAK_SYSTEM_PACKAGES=1
pip3 install mpmath==1.3.0 -q
python3 /solution/solver.py
