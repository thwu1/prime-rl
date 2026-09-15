#!/usr/bin/env python3
"""
Generate reference binary files for canonical ABI conformance testing.
Pre-computed correct serializations from a known-correct implementation.
"""
import os
import json

os.makedirs('/app/reference', exist_ok=True)

# Pre-computed correct canonical ABI byte serializations (hex encoded)
refs = {
    'lower_point2d.bin': {
        'hex': '0000c03f000010c0',
        'description': 'point2d {x: 1.5, y: -2.25}',
        'size': 8,
    },
    'lower_error-info_code_404.bin': {
        'hex': '010000009401000000000000',
        'description': 'error-info code(404)',
        'size': 12,
    },
    'lower_maybe-value_some_2.5.bin': {
        'hex': '01000000000000000000000000000440',
        'description': 'maybe-value some(2.5)',
        'size': 16,
    },
    'lower_mixed-align.bin': {
        'hex': '01000000000000000000000000000840e803000000000000',
        'description': 'mixed-align {flag: true, value: 3.0, tag: 1000}',
        'size': 24,
    },
    'lower_direction_south.bin': {
        'hex': '02',
        'description': 'direction south (discriminant index 2)',
        'size': 1,
    },
    'lower_nested-opt_some_some_42.bin': {
        'hex': '010000000000000001000000000000000000000000004540',
        'description': 'option<option<f64>> some(some(42.0))',
        'size': 24,
    },
    'lower_complex-variant_compound.bin': {
        'hex': '050000000000000064000000000000000000000000000440',
        'description': 'complex-variant compound(100, 2.5)',
        'size': 24,
    },
    'lower_error-info_none.bin': {
        'hex': '000000000000000000000000',
        'description': 'error-info none (all zeros)',
        'size': 12,
    },
}

# Write binary files
for name, info in refs.items():
    with open(f'/app/reference/{name}', 'wb') as f:
        f.write(bytes.fromhex(info['hex']))

# Write manifest
manifest = {
    name: {'description': info['description'], 'size': info['size'], 'hex': info['hex']}
    for name, info in refs.items()
}
with open('/app/reference/manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)

print(f"Generated {len(refs)} reference files in /app/reference/")
