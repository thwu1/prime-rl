#!/bin/bash

pip3 install propka==3.5.1 -q

cp /solution/pka_engine.py /app/pka_engine.py

# Verify it works on all three PDB files
python3 /app/pka_engine.py /app/data/sample-issue-140.pdb
python3 /app/pka_engine.py /app/data/3SGB.pdb
python3 /app/pka_engine.py /app/data/1HPX.pdb
