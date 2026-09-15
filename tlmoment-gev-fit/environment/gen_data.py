"""Generate synthetic GEV datasets with known parameters for the task.
Some datasets have contamination from sensor errors or recording anomalies.
Uses only Python standard library (no numpy) for Docker build reliability."""
import random
import math


def gev_ppf(u, xi, mu, sigma):
    """GEV quantile function (inverse CDF)."""
    if abs(xi) < 1e-10:
        return mu - sigma * math.log(-math.log(u))
    return mu + sigma * ((-math.log(u)) ** (-xi) - 1) / xi


random.seed(2024)

# Station A: Frechet (xi=0.2, sigma=10, mu=50), n=800, clean
with open('/data/station_A.csv', 'w') as f:
    for _ in range(800):
        u = random.random()
        while u < 1e-15 or u > 1 - 1e-15:
            u = random.random()
        f.write(f"{gev_ppf(u, 0.2, 50.0, 10.0):.18e}\n")

# Station B: Gumbel (xi=0, sigma=8, mu=25), n=800, clean
with open('/data/station_B.csv', 'w') as f:
    for _ in range(800):
        u = random.random()
        while u < 1e-15 or u > 1 - 1e-15:
            u = random.random()
        f.write(f"{gev_ppf(u, 0.0, 25.0, 8.0):.18e}\n")

# Station C: Weibull (xi=-0.15, sigma=5, mu=100), n=800, clean
with open('/data/station_C.csv', 'w') as f:
    for _ in range(800):
        u = random.random()
        while u < 1e-15 or u > 1 - 1e-15:
            u = random.random()
        f.write(f"{gev_ppf(u, -0.15, 100.0, 5.0):.18e}\n")

# Station D: Frechet (xi=0.1, sigma=7, mu=40), n=800, 5% contamination
# Contamination: replace 40 values with draws from a much heavier-tailed GEV
data_d = []
for _ in range(800):
    u = random.random()
    while u < 1e-15 or u > 1 - 1e-15:
        u = random.random()
    data_d.append(gev_ppf(u, 0.1, 40.0, 7.0))
idx_d = random.sample(range(800), 40)
for i in idx_d:
    u_c = random.uniform(0.85, 0.999)
    data_d[i] = gev_ppf(u_c, 0.6, 40.0, 25.0)
with open('/data/station_D.csv', 'w') as f:
    for v in data_d:
        f.write(f"{v:.18e}\n")

# Station E: Weibull (xi=-0.2, sigma=6, mu=80), n=800, 3% contamination
# Contamination: add large positive offsets (sensor malfunction)
data_e = []
for _ in range(800):
    u = random.random()
    while u < 1e-15 or u > 1 - 1e-15:
        u = random.random()
    data_e.append(gev_ppf(u, -0.2, 80.0, 6.0))
idx_e = random.sample(range(800), 24)
for i in idx_e:
    data_e[i] = data_e[i] + 40.0 + random.expovariate(1.0 / 20.0)
with open('/data/station_E.csv', 'w') as f:
    for v in data_e:
        f.write(f"{v:.18e}\n")
