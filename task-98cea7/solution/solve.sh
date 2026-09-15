#!/bin/bash


pip3 install numpy==2.1.3 -q

# Deploy the optimizer implementation
python3 /solution/deploy_solver.py

# Deploy the Makefile for the benchmark pipeline
python3 /solution/deploy_pipeline.py

# Run the full benchmark pipeline (benchmark + report)
cd /app && make all
