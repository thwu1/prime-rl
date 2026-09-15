#!/bin/bash

set -e

pip3 install numpy==2.1.3 scipy==1.14.1 --no-cache-dir -q

cp /solution/audit_solver.py /app/audit_solver.py
cd /app
python3 /app/audit_solver.py
