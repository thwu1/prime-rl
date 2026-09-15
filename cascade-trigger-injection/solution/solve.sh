#!/bin/bash

pip3 install psycopg2-binary==2.9.10 -q

# Ensure PostgreSQL is running and schema is loaded (safety net)
/app/ensure_db.sh

# Run analysis, generate fixes, and apply
python3 /solution/fix_functions.py
