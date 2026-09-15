#!/usr/bin/env bash

set -euo pipefail

# Fix the buggy SPSC queue
python3 /solution/fix_queue.py

# Create the batch queue implementation
python3 /solution/create_batch_queue.py

# Verify the fixes compile and the main binary passes
make -C /app clean all
/app/market_feed
echo "Solution applied and verified."
