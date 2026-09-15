#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cd /app

# Generate FRF data
python3 /app/generate_frf.py

# Deploy the modal analysis module
cp /solution/modal_analysis_impl.py /app/modal_analysis.py
