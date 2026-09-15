#!/usr/bin/env python3
"""
Validation oracle: generates reference outputs from pyTMD's OTIS model.
Install pyTMD first, then run this script to produce reference data
for debugging your tidal_engine implementation.

Usage:
    pip3 install pyTMD
    python3 /app/validation_oracle.py
"""
import json
import sys
import numpy as np

try:
    import pyTMD.astro
    import pyTMD.constituents
except ImportError:
    print("ERROR: pyTMD not installed.")
    print("Run: pip3 install pyTMD")
    sys.exit(1)

data = {}

# Mean longitudes at several MJDs
mjds = [51544.4993, 55000.0, 58000.0, 59000.0, 60000.0]
for m in mjds:
    s, h, p, n, ps = pyTMD.astro.mean_longitudes(
        np.array([m]), method='Cartwright'
    )
    data[f'mean_longitudes_{m}'] = {
        's': round(float(np.mod(s[0], 360)), 6),
        'h': round(float(np.mod(h[0], 360)), 6),
        'p': round(float(np.mod(p[0], 360)), 6),
        'n': round(float(np.mod(n[0], 360)), 6),
        'ps': round(float(np.mod(ps[0], 360)), 6),
    }

# Equilibrium arguments and nodal corrections
test_constituents = [
    'm2', 's2', 'k1', 'o1', 'n2', 'k2', 'q1', 'p1', 'mf', 'mm',
    'm1', 'l2', '2n2', 'mu2', 'eta2', 'm4', 'ms4', 'mk3', 'm3',
    'oo1', 'chi1', 'j1', 'sa', 'ssa', 'mt', 'm6', 'm8',
]
test_mjd = np.array([59000.0])
try:
    pu, pf, G = pyTMD.constituents.arguments(
        test_mjd, test_constituents, corrections='OTIS', M1='Ray'
    )
except TypeError:
    pu, pf, G = pyTMD.constituents.arguments(
        test_mjd, test_constituents, corrections='OTIS'
    )
for i, c in enumerate(test_constituents):
    data[f'constituent_{c}'] = {
        'argument_deg': round(float(G[0, i]), 4),
        'nodal_phase_rad': round(float(pu[0, i]), 6),
        'nodal_factor': round(float(pf[0, i]), 6),
    }

outfile = '/app/reference_data.json'
with open(outfile, 'w') as f:
    json.dump(data, f, indent=2)
print(f"Reference data: {len(data)} entries written to {outfile}")
print("Compare your tidal_engine.py outputs against these values.")
