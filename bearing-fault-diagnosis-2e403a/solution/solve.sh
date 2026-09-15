#!/usr/bin/env bash


set -e

pip3 install numpy==1.26.4 scipy==1.13.1 -q

mkdir -p /app/bearing_diagnostics

cp /solution/init_pkg.py   /app/bearing_diagnostics/__init__.py
cp /solution/defect_freq.py /app/bearing_diagnostics/defect_freq.py
cp /solution/envelope_mod.py /app/bearing_diagnostics/envelope.py
cp /solution/diagnose_mod.py /app/bearing_diagnostics/diagnose.py
