
import random
import json
import os

random.seed(42)
os.makedirs('/app/data', exist_ok=True)

streams = {}
manifest = {}

# Stream 1: Normal, mean shift 0 -> 0.5 at t=500
s1 = [random.gauss(0, 1) for _ in range(500)]
s1 += [random.gauss(0.5, 1) for _ in range(500)]
streams['stream_1'] = s1
manifest['stream_1'] = {
    'family': 'normal', 'null_mean': 0.0, 'null_std': 1.0,
    'length': 1000
}

# Stream 2: Normal with non-unit variance, mean shift 0 -> 2.0 at t=300
s2 = [random.gauss(0, 2) for _ in range(300)]
s2 += [random.gauss(2.0, 2) for _ in range(700)]
streams['stream_2'] = s2
manifest['stream_2'] = {
    'family': 'normal', 'null_mean': 0.0, 'null_std': 2.0,
    'length': 1000
}

# Stream 3: Bernoulli, proportion shift 0.5 -> 0.7 at t=400
s3 = [1.0 if random.random() < 0.5 else 0.0 for _ in range(400)]
s3 += [1.0 if random.random() < 0.7 else 0.0 for _ in range(400)]
streams['stream_3'] = s3
manifest['stream_3'] = {
    'family': 'bernoulli', 'null_proportion': 0.5,
    'length': 800
}

# Stream 4: Normal, stationary (no change)
s4 = [random.gauss(0, 1) for _ in range(800)]
streams['stream_4'] = s4
manifest['stream_4'] = {
    'family': 'normal', 'null_mean': 0.0, 'null_std': 1.0,
    'length': 800
}

# Stream 5: Normal, large mean shift 0 -> 2.0 at t=200
s5 = [random.gauss(0, 1) for _ in range(200)]
s5 += [random.gauss(2.0, 1) for _ in range(300)]
streams['stream_5'] = s5
manifest['stream_5'] = {
    'family': 'normal', 'null_mean': 0.0, 'null_std': 1.0,
    'length': 500
}

with open('/app/data/streams.json', 'w') as f:
    json.dump(streams, f)

with open('/app/data/manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)

print("Data generated successfully.")
