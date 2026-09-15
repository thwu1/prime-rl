#!/bin/bash

set -e

# Install solution dependencies
pip3 install dbt-duckdb==1.8.4 duckdb==1.5.3 -q

# Apply all fixes and create missing components
python3 /solution/fix_project.py

# Build the project (first run creates all objects)
cd /app/dbt_project
dbt clean
dbt build --full-refresh

# Build again to validate incremental model behavior
dbt build
