#!/bin/bash

python3 /solution/solve.py

echo "--- Validating output ---"
validate-output /app/output.txt
