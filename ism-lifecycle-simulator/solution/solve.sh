#!/bin/bash

# Copy solution files to /app and run the forensics pipeline
cp /solution/run_forensics.sh /app/run_forensics.sh
cp /solution/forensics.py /app/forensics.py
chmod +x /app/run_forensics.sh

cd /app
bash /app/run_forensics.sh
