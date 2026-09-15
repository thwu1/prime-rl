#!/bin/bash

# Step 1: Fix bugs in the base MOESI simulator
python3 /solution/fix_moesi.py

# Step 2: Install the NUMA coherence simulator (includes CLI mode)
cp /solution/numa_coherence_impl.py /app/numa_coherence.py

# Step 3: Install and run the comparison script
cp /solution/run_comparison.sh /app/run_comparison.sh
chmod +x /app/run_comparison.sh
bash /app/run_comparison.sh
