#!/bin/bash

# Fix all bugs in the evaluation pipeline and generate audit report
python3 /solution/fix_pipeline.py

# Deploy the pipeline validator
cp /solution/pipeline_validator.py /app/pipeline_validator.py

# Run the fixed pipeline via Makefile
cd /app && make eval

# Verify the validator passes on the fixed pipeline
python3 /app/pipeline_validator.py
