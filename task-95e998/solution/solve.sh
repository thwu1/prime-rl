#!/bin/bash

# Copy and run the corrected evaluation script
cp /solution/compute_correct.py /app/compute_correct.py
cd /app
python3 compute_correct.py
