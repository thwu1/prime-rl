#!/bin/bash

# 1.8.dev13 was removed from the package index; dev14 is the next compatible
# release and exposes the same WCNF/RC2 API used by the reference solver.
pip3 install python-sat==1.8.dev14 -q

cd /app
python3 /solution/solver.py
