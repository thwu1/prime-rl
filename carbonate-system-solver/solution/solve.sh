#!/bin/bash

set -e

pip3 install numpy==2.1.3 scipy==1.14.1 pandas==2.2.3 PyCO2SYS==1.8.3 -q

# Step 1: Diagnose and fix bugs in the carbonate solver
python3 /solution/diagnose_and_fix.py

# Step 2: Process cruise data and perform crossover QC
python3 /solution/crossover_qc.py

echo "Solution complete."
