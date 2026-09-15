#!/usr/bin/env python3
"""Generate ZPK data files from elliptic_filter module for the freqresp analyzer."""
import json
import sys
import os

sys.path.insert(0, '/app')
import numpy as np
import elliptic_filter

specs = json.load(open('/app/filter_specs.json'))
for spec in specs:
    N = spec['N']
    Rp = spec['Rp']
    Rs = spec['Rs']
    try:
        z, p, k = elliptic_filter.elliptic_filter_poles_zeros(N, Rp, Rs)
        z = np.array(z, dtype=complex)
        p = np.array(p, dtype=complex)
        fname = '/app/zpk_N%d_Rp%.1f_Rs%.1f.txt' % (N, Rp, Rs)
        with open(fname, 'w') as f:
            f.write('%d %d %.15e\n' % (len(z), len(p), float(k)))
            for zi in z:
                f.write('%.15e %.15e\n' % (zi.real, zi.imag))
            for pi in p:
                f.write('%.15e %.15e\n' % (pi.real, pi.imag))
        print('Written: %s' % fname)
    except Exception as e:
        print('ERROR for N=%d, Rp=%.1f, Rs=%.1f: %s' % (N, Rp, Rs, e), file=sys.stderr)
