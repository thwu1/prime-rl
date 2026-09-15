#!/bin/bash

# Fix all bugs and implement stubs in the obstetric pipeline
python3 /solution/fix_pipeline.py

# Run the corrected pipeline
Rscript /app/run_pipeline.R
