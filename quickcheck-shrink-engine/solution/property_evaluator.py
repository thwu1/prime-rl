#!/usr/bin/env python3
"""Evaluate merge_intervals properties and write classifications."""

import sys
import json

sys.path.insert(0, "/app")

from merge import (
    merge_intervals_v1, merge_intervals_v2,
    prop_idempotent, prop_covers_all, prop_no_growth, prop_each_preserved,
)

# Diverse test inputs covering edge cases
test_inputs = [
    [],
    [(0, 1)],
    [(0, 2), (1, 3)],
    [(0, 3), (1, 2)],
    [(0, 5), (1, 3), (2, 4)],
    [(0, 1), (1, 2), (2, 3)],
    [(0, 2), (3, 5)],
    [(0, 10), (1, 2), (3, 4), (5, 6)],
]

properties = {
    "prop_idempotent": prop_idempotent,
    "prop_covers_all": prop_covers_all,
    "prop_no_growth": prop_no_growth,
    "prop_each_preserved": prop_each_preserved,
}

results = {}
for name, prop in properties.items():
    v1_passes = all(prop(merge_intervals_v1, inp) for inp in test_inputs)
    v2_passes = all(prop(merge_intervals_v2, inp) for inp in test_inputs)

    if not v1_passes:
        results[name] = "strong"
    elif v2_passes:
        results[name] = "weak"
    else:
        results[name] = "sound"

with open("/app/property_audit_results.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"Property audit results: {results}")
