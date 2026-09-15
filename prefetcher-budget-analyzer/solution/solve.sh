#!/bin/bash

# Copy reference solution and run it
cp /solution/analyze.py /app/analyze.py
chmod +r /app/analyze.py
cd /app
python3 /app/analyze.py
