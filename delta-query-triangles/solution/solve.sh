#!/bin/bash

pip3 install duckdb==1.0.0 -q
cp /solution/incremental.py /app/incremental.py
python3 /app/incremental.py
