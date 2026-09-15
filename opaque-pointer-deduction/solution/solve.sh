#!/bin/bash

# Deploy the complete type deduction analysis tool
cp /solution/solver.py /app/type_deducer.py
cd /app
python3 /app/type_deducer.py
