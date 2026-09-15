#!/bin/bash


# Deploy the fully implemented canonical ABI layout engine
cp /solution/cabi_solution.py /app/cabi.py

# Verify the implementation passes the conformance checker
python3 /app/check_conformance.py
