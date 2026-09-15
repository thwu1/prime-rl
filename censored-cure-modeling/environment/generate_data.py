"""Generate synthetic censored conversion data from Weibull cure models."""
import random
import csv
import os
import math

random.seed(42)

_P = [0x2A, 0x1E, 0x0F, 0x44, 0x0F, 0x14]
GROUPS = {
    'A': {'c': _P[0] / 100, 'lam': _P[1] / 1000, 'p': _P[2] / 10},
    'B': {'c': _P[3] / 100, 'lam': _P[4] / 1000, 'p': _P[5] / 10},
}
N = 2000
OBS_WINDOW = 180.0

os.makedirs('/app/data', exist_ok=True)

with open('/app/data/conversions.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['user_id', 'group', 'created_at', 'converted_at', 'observed_at'])
    uid = 1
    for g in sorted(GROUPS):
        params = GROUPS[g]
        c, lam, p = params['c'], params['lam'], params['p']
        for _ in range(N):
            created = random.uniform(0, OBS_WINDOW)
            max_t = OBS_WINDOW - created
            if random.random() < c:
                u = random.random()
                delay = (-math.log(1 - u)) ** (1.0 / p) / lam
                if delay <= max_t:
                    w.writerow([uid, g, round(created, 2),
                                round(created + delay, 2), OBS_WINDOW])
                else:
                    w.writerow([uid, g, round(created, 2), '', OBS_WINDOW])
            else:
                w.writerow([uid, g, round(created, 2), '', OBS_WINDOW])
            uid += 1
