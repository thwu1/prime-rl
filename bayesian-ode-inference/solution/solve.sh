#!/bin/bash

# Replace buggy model with corrected version, then run inference
cp /solution/model_fixed.py /app/model.py
cd /app
python3 model.py
