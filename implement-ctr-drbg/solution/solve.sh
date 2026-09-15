#!/bin/bash

# Install dependencies
pip3 install pycryptodome==3.21.0 -q

# Deploy the reference implementation, parser, and harness
cp /solution/reference_impl.py /app/reference_impl.py
cp /solution/cavs_parser.py /app/cavs_parser.py
cp /solution/harness.py /app/harness.py

# Generate the conformance report by running the harness
python3 /solution/generate_report.py
