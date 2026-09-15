"""Generate deterministic test datasets for the parallel statistics pipeline."""

import random
import os


def generate_datasets(data_dir):
    os.makedirs(data_dir, exist_ok=True)

    # Dataset 1: Uniform [0, 1000], 10000 values
    rng = random.Random(42)
    with open(os.path.join(data_dir, 'uniform.csv'), 'w') as f:
        for _ in range(10000):
            f.write(f"{rng.uniform(0, 1000):.15g}\n")

    # Dataset 2: Normal(100, 25), 10000 values
    rng = random.Random(123)
    with open(os.path.join(data_dir, 'normal.csv'), 'w') as f:
        for _ in range(10000):
            f.write(f"{rng.gauss(100, 25):.15g}\n")

    # Dataset 3: Exponential(mean=10), 10000 values
    rng = random.Random(456)
    with open(os.path.join(data_dir, 'skewed.csv'), 'w') as f:
        for _ in range(10000):
            f.write(f"{rng.expovariate(0.1):.15g}\n")

    # Dataset 4: Bimodal (alternating Normal(10,2) and Normal(90,2)), 10000 values
    rng = random.Random(789)
    with open(os.path.join(data_dir, 'bimodal.csv'), 'w') as f:
        for i in range(10000):
            if i % 2 == 0:
                f.write(f"{rng.gauss(10, 2):.15g}\n")
            else:
                f.write(f"{rng.gauss(90, 2):.15g}\n")


if __name__ == '__main__':
    generate_datasets('/app/data')
