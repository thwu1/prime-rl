#!/bin/bash

# Fix and extend the dbt pipeline
python3 /solution/build_pipeline.py

# Run dbt build to verify
cd /app/dbt_project
dbt build
