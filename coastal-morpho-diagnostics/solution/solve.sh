#!/bin/bash

set -e

pip3 install numpy==1.26.4 charset-normalizer==3.4.1 -q

# Fix Fortran source (ASCII encoding + assumed-shape arrays) and compile with f2py
cp /solution/sedtrans_fixed.f90 /app/fortran/sedtrans.f90
cd /app
python3 -m numpy.f2py -c /app/fortran/sedtrans.f90 -m sedtrans 2>&1

# Deploy fixed Python modules
mkdir -p /app/coastal_diag
cp /solution/impl_init.py /app/coastal_diag/__init__.py
cp /solution/impl_profiles.py /app/coastal_diag/profiles.py
cp /solution/impl_spectra.py /app/coastal_diag/spectra.py
cp /solution/impl_metrics.py /app/coastal_diag/metrics.py
cp /solution/impl_verification.py /app/coastal_diag/verification.py
cp /solution/impl_cli.py /app/coastal_diag/cli.py

# Run diagnostics
mkdir -p /app/output
python3 /app/coastal_diag/cli.py --config /app/data/config.json --output /app/output/report.json
