#!/bin/bash

pip3 install pymatching==2.3.1 numpy==1.26.4 -q

cp /solution/toric_decoder.py /app/toric_decoder.py

cd /app
python3 -c "
import toric_decoder as td
import numpy as np

# Verify matching graph structure
for d in [3, 5, 7]:
    zm = td.build_z_matching(d, 0.1)
    xm = td.build_x_matching(d, 0.1)
    assert zm.num_nodes == d*d
    assert zm.num_edges == 2*d*d
    assert zm.num_fault_ids == 2
    assert len(zm.boundary) == 0
    assert xm.num_nodes == d*d
    assert xm.num_edges == 2*d*d
    print(f'd={d}: Z matching {zm.num_nodes} nodes, {zm.num_edges} edges OK')

# Verify all single-error decodings for d=5
d = 5
zm = td.build_z_matching(d, 0.1)
for q in range(2*d*d):
    x = np.zeros((1, 2*d*d), dtype=np.uint8)
    x[0, q] = 1
    syn = td.z_syndrome(d, x)
    actual = td.actual_x_observables(d, x)
    pred = zm.decode_batch(syn)
    assert np.array_equal(pred, actual), f'Z decode failed qubit {q}'
print('All single X-error decodings correct (d=5)')

xm = td.build_x_matching(d, 0.1)
for q in range(2*d*d):
    z = np.zeros((1, 2*d*d), dtype=np.uint8)
    z[0, q] = 1
    syn = td.x_syndrome(d, z)
    actual = td.actual_z_observables(d, z)
    pred = xm.decode_batch(syn)
    assert np.array_equal(pred, actual), f'X decode failed qubit {q}'
print('All single Z-error decodings correct (d=5)')

# Verify logical error rate behavior
rate = td.logical_error_rate(5, 0.05, 3000, seed=42)
print(f'Logical error rate (d=5, p=0.05): {rate:.4f}')
assert rate < 0.05
print('Solution verified successfully.')
"
