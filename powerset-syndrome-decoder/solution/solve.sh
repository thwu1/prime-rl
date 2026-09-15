#!/bin/bash

# Deploy the syndrome decoder implementation
cp /solution/decoder_impl.py /app/decoder.py

# Verify the decoder works by running it on test cases
cd /app
python3 -c "
import math
from decoder import SyndromeDecoder

# --- Test 1: Chain DEM parsing and single-error decoding ---
chain_dem = '''error(0.10) D0 D1 L0
error(0.05) D1 D2
error(0.08) D2 D3 L1
error(0.12) D3 D4'''

dec = SyndromeDecoder(chain_dem, beam_width=20, pq_limit=1000000)
assert dec.num_errors == 4, f'Expected 4 errors, got {dec.num_errors}'
assert dec.num_detectors == 5, f'Expected 5 detectors, got {dec.num_detectors}'
assert dec.num_observables == 2, f'Expected 2 observables, got {dec.num_observables}'

r = dec.decode([0, 1])
assert r['errors'] == [0], f'Expected [0], got {r[\"errors\"]}'
assert r['observables'] == [0], f'Expected [0], got {r[\"observables\"]}'
assert math.isclose(r['cost'], math.log(9), rel_tol=1e-6), f'Cost {r[\"cost\"]} != log(9)'

# --- Test 2: Multi-error decoding ---
r = dec.decode([0, 1, 2, 3])
assert r['errors'] == [0, 2], f'Expected [0, 2], got {r[\"errors\"]}'
assert r['observables'] == [0, 1], f'Expected [0, 1], got {r[\"observables\"]}'

# --- Test 3: Empty syndrome ---
r = dec.decode([])
assert r['errors'] == []
assert r['cost'] == 0.0

# --- Test 4: Boundary DEM - 2-error cheaper than 1-error ---
boundary_dem = '''error(0.10) D0 D1
error(0.05) D1 D2
error(0.08) D2 D3
error(0.15) D0 D3
error(0.03) D0 L0
error(0.12) D1
error(0.07) D2 L1
error(0.20) D3'''

dec2 = SyndromeDecoder(boundary_dem, beam_width=20, pq_limit=1000000)
r = dec2.decode([0])
single_cost = -math.log(0.03 / 0.97)
assert r['cost'] < single_cost, f'Should find cheaper 2-error solution: {r[\"cost\"]} >= {single_cost}'

# --- Test 5: Grid DEM optimality ---
grid_dem = '''error(0.10) D0 D1
error(0.05) D0 D2 L0
error(0.08) D1 D3
error(0.15) D2 D3 L1
error(0.03) D1 D2
error(0.20) D0 D3 L0 L1'''

dec3 = SyndromeDecoder(grid_dem, beam_width=20, pq_limit=1000000)
r = dec3.decode([0, 3])
assert math.isclose(r['cost'], math.log(4), rel_tol=1e-6), f'Cost mismatch: {r[\"cost\"]} != log(4)'

# --- Test 6: Stim integration ---
import stim
circuit = stim.Circuit.generated(
    'repetition_code:memory',
    distance=5,
    rounds=1,
    after_clifford_depolarization=0.01
)
dem = circuit.detector_error_model(decompose_errors=True)
lines = []
for inst in dem.flattened():
    if inst.type == 'error':
        prob = inst.args_copy()[0]
        targets = inst.targets_copy()
        if any(t.is_separator() for t in targets):
            continue
        parts = []
        for t in targets:
            if t.is_relative_detector_id():
                parts.append(f'D{t.val}')
            elif t.is_logical_observable_id():
                parts.append(f'L{t.val}')
        if parts and 0 < prob < 1:
            lines.append(f'error({prob}) {\" \".join(parts)}')
stim_dem_text = chr(10).join(lines)

dec4 = SyndromeDecoder(stim_dem_text, beam_width=20, pq_limit=500000)
assert dec4.num_errors > 0, 'Failed to parse stim DEM'
r = dec4.decode([])
assert r['errors'] == [], 'Empty syndrome should return no errors'

# --- Test 7: Surface code X-basis ---
circuit_x = stim.Circuit.generated(
    'surface_code:rotated_memory_x',
    distance=3,
    rounds=1,
    after_clifford_depolarization=0.001
)
dem_x = circuit_x.detector_error_model(decompose_errors=True)
lines_x = []
for inst in dem_x.flattened():
    if inst.type == 'error':
        prob = inst.args_copy()[0]
        targets = inst.targets_copy()
        if any(t.is_separator() for t in targets):
            continue
        parts = []
        for t in targets:
            if t.is_relative_detector_id():
                parts.append(f'D{t.val}')
            elif t.is_logical_observable_id():
                parts.append(f'L{t.val}')
        if parts and 0 < prob < 1:
            lines_x.append(f'error({prob}) {\" \".join(parts)}')
stim_dem_x = chr(10).join(lines_x)

dec5 = SyndromeDecoder(stim_dem_x, beam_width=15, pq_limit=500000)
assert dec5.num_errors > 0, 'Failed to parse stim X-basis surface code DEM'

print('All decoder verification tests passed')
"
