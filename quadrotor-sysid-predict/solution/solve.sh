#!/bin/bash

# Install solution dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Deploy implementations
cp /solution/dynamics_impl.py /app/dynamics.py
cp /solution/integrator_impl.py /app/integrator.py
cp /solution/sysid_impl.py /app/sysid.py

# Run prediction pipeline
cd /app
python3 /app/predict.py
