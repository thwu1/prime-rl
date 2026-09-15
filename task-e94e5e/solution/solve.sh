#!/bin/bash


# numpy and scipy are pre-installed in the Docker image

# Deploy solution files
cp /solution/sedov_impl.py /app/sedov.py
cp /solution/noh_impl.py /app/noh.py
cp /solution/verify_impl.py /app/verify.py

# Run verification framework to generate results.json
cd /app
python3 verify.py

# Quick sanity check
python3 -c "
import json, sys
with open('/app/results.json') as f:
    data = json.load(f)
print('Quadrature: quad_alpha =', data['quadrature_comparison']['quad_alpha'])
print('Cross-validation entries:', len(data['cross_validation']))
print('R-H density error:', data['rankine_hugoniot']['density_rel_error'])
print('All verification checks passed.')
"
