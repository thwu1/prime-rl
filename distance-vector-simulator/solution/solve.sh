#!/bin/bash

# Deploy the fixed router and generate correct output
cp /solution/fixed_router.py /app/dv_router.py
cd /app
python3 /app/dv_router.py
