#!/bin/bash

pip3 install scikit-learn==1.6.1 numpy==2.1.3 -q

# Generate data
python3 /app/generate_data.py

# Deploy corrected solution
cp /solution/evaluate_impl.py /app/evaluate.py

# Run
python3 /app/evaluate.py
