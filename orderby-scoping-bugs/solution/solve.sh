#!/bin/bash

# Start PostgreSQL
pg_ctlcluster 16 main start
sleep 2

# Run the analysis and fix tool
python3 /solution/fix_queries.py
