#!/bin/bash

cd /app

# Step 1: Create and run tshark extraction script
cp /solution/tshark_extract.sh /app/tshark_extract.sh
chmod +x /app/tshark_extract.sh
bash /app/tshark_extract.sh

# Step 2: Fix tc configuration bugs
python3 /solution/tc_fix.py

# Step 3: Deploy shaper implementation
cp /solution/shaper_impl.py /app/shaper.py

# Step 4: Run the shaper pipeline
python3 /app/run_shaper.py
