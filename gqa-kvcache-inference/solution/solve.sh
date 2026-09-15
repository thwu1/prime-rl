#!/bin/bash

# Deploy optimized inference module
cp /solution/kv_inference_solution.py /app/kv_inference.py

# Deploy and run profiling/benchmarking script
cp /solution/profile_report_solution.py /app/profile_report.py
cd /app && python3 /app/profile_report.py
