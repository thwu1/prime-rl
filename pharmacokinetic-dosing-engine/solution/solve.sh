#!/bin/bash


cd /app

# Deploy PK engine and run it
cp /solution/solver.py /app/pk_engine.py
python3 /app/pk_engine.py

# Deploy validation script and run it
cp /solution/validate_script.sh /app/validate.sh
chmod +x /app/validate.sh
bash /app/validate.sh
