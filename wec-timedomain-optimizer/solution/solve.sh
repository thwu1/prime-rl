#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cd /app

# Verify input files exist
echo "Checking input files..."
ls -la /app/config.json /app/hydro_data.json
python3 -c "import json; c=json.load(open('/app/config.json')); print('config keys:', sorted(c.keys()))"

python3 /solution/wec_solver.py
