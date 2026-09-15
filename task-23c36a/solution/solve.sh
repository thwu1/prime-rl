#!/bin/bash

export PIP_BREAK_SYSTEM_PACKAGES=1
python3 -m pip install -q pycryptodome==3.21.0 2>&1

python3 /solution/solver.py
