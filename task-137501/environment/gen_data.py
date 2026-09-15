"""Generate synthetic censored conversion data for survival analysis task."""
import random
import csv
import os
import math

random.seed(20240101)

os.makedirs('/app/data', exist_ok=True)


def weibull_sample(lam, p):
    """Sample from Weibull with CDF = 1 - exp(-(lam*t)^p)."""
    u = random.random()
    while u == 0.0:
        u = random.random()
    return (-math.log(u)) ** (1.0 / p) / lam


def poisson_sample(lam):
    """Sample from Poisson distribution."""
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= random.random()
        if p < L:
            return k - 1


channels = {
    'A': {'c': 0.35, 'lam': 0.05, 'p': 1.5},
    'B': {'c': 0.25, 'lam': 0.03, 'p': 1.0},
    'C': {'c': 0.45, 'lam': 0.02, 'p': 0.8},
}

max_obs = 180
n_weeks = 26
users_per_week = 80

rows = []
uid = 0

for ch_name in sorted(channels.keys()):
    params = channels[ch_name]
    c, lam, p = params['c'], params['lam'], params['p']
    for week_idx in range(n_weeks):
        cohort = "2024-W{:02d}".format(week_idx + 1)
        obs_window = max_obs - week_idx * 7
        if obs_window <= 0:
            continue
        n = poisson_sample(users_per_week)
        for _ in range(n):
            uid += 1
            if random.random() < c:
                t = max(weibull_sample(lam, p), 0.01)
                if t <= obs_window:
                    rows.append([uid, cohort, ch_name, 1, round(t, 2)])
                else:
                    rows.append([uid, cohort, ch_name, 0, obs_window])
            else:
                rows.append([uid, cohort, ch_name, 0, obs_window])

with open('/app/data/conversions.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['user_id', 'cohort_week', 'channel', 'converted', 'days_to_event'])
    for row in rows:
        writer.writerow(row)

print("Generated {} rows across {} channels".format(len(rows), len(channels)))
