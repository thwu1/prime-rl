#!/usr/bin/env bash

set -e

pip3 install numpy==2.1.3 Pillow==11.1.0 -q

# Deploy the fixed evaluator, completed generator, and fixed Makefile
cp /solution/evaluate.py /app/src/evaluate.py
cp /solution/generate_synthetic.py /app/src/generate_synthetic.py
cp /solution/Makefile /app/Makefile

chmod +x /app/src/evaluate.py
chmod +x /app/src/generate_synthetic.py

echo "Solution deployed: fixed evaluator, generator, and Makefile at /app/"
