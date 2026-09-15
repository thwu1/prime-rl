"""Generate randomized task configuration (task DNA) at Docker build time."""
import json
import os
import random

random.seed(os.urandom(16))

seed_values = sorted(random.sample(range(100), 5))
bedroc_alpha = random.choice([10.0, 20.0, 80.5, 160.9])
ef_percentage = random.choice([1, 5, 10])
n_pains = random.randint(1, 3)
pains_variants = sorted(random.sample(["A", "B", "C"], n_pains))
test_size = random.choice([0.15, 0.2, 0.25])

config = {
    "seed_values": seed_values,
    "bedroc_alpha": bedroc_alpha,
    "ef_percentage": ef_percentage,
    "pains_variants": pains_variants,
    "test_size": test_size,
}

os.makedirs("/app", exist_ok=True)
with open("/app/task_config.json", "w") as f:
    json.dump(config, f, indent=2)

print(f"Task config generated: {json.dumps(config)}")
