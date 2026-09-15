#!/bin/bash

# Build the correct database using business rules
python3 /solution/build_db.py

# Generate the audit report by comparing against buggy spec implementation
python3 /solution/compare_and_audit.py
