#!/bin/bash

pip3 install pycryptodome==3.20.0 -q
mkdir -p /app/output
cp /solution/hybrid_router_template.py /app/output/hybrid_router.py
python3 /solution/solver.py
