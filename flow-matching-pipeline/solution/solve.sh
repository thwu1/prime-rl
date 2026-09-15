#!/bin/bash

# Copy correct pipeline to app directory
cp /solution/pipeline.py /app/pipeline.py

# Verify with validate.py
python3 /app/validate.py
