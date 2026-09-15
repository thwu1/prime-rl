#!/bin/bash

pip3 install scipy==1.14.1 -q

# Create the parameter database
python3 /app/create_params_db.py

# Deploy the calculator
cp /solution/simm_v25.py /app/simm_calc.py
chmod +x /app/simm_calc.py

# Run on all CRIF files
for f in /app/crif/C*_crif.csv; do
    python3 /app/simm_calc.py "$f"
done
