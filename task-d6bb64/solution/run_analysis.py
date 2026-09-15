#!/usr/bin/env python3

"""Run minimum-order analysis across all scenarios and write results.json."""

import json
import sys

sys.path.insert(0, "/app")
from digitize import min_order_for_spec

with open("/app/scenarios.json") as f:
    scenarios = json.load(f)

results = {}
for name, spec in scenarios.items():
    order, ripple, atten = min_order_for_spec(
        spec["passband_hz"],
        spec["stopband_hz"],
        spec["ripple_db"],
        spec["atten_db"],
        spec["sample_rate_hz"],
    )
    results[name] = {
        "min_order": order,
        "ripple_db": round(ripple, 6),
        "atten_db": round(atten, 6),
    }
    print(f"  {name}: order={order}, ripple={ripple:.4f} dB, atten={atten:.4f} dB")

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("\nResults written to /app/results.json")
