#!/usr/bin/env bash

cd /app

# Copy and run the reconciler
cp /solution/reconciler.py /app/reconciler.py
python3 /app/reconciler.py
