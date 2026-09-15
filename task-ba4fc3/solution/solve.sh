#!/bin/bash

# No extra pip dependencies needed for the solution (stdlib only)

cp /solution/rbt_pool_impl.py /app/rbt_pool.py
chmod +x /app/rbt_pool.py

# Verify the tool loads and shows help
python3 /app/rbt_pool.py --help
