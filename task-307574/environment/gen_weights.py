"""Generate deterministic weight data for the NF4 reverse engineering task."""
import random
import json

random.seed(42)
weights = [random.gauss(0, 1) for _ in range(4096)]
with open('/app/weights.json', 'w') as f:
    json.dump(weights, f)
