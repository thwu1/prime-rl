#!/bin/bash

set -e

# Copy the auditor into /app and run it
cp /solution/audit.py /app/audit.py
cd /app
python3 /app/audit.py
