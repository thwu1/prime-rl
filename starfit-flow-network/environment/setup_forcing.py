#!/usr/bin/env python3
"""Generate forcing data (lateral inflows) for the STARFIT reservoir network."""
import csv
import math
import os

os.makedirs('/app/forcing', exist_ok=True)

n_days = 365

with open('/app/forcing/inflows.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['day', 'node_0', 'node_1', 'node_2', 'node_3', 'node_4'])
    for d in range(1, n_days + 1):
        inflows = [
            50.0 + 30.0 * math.sin(2.0 * math.pi * d / 365.0) + 10.0 * math.sin(4.0 * math.pi * d / 365.0),
            5.0,
            8.0,
            3.0,
            20.0 + 15.0 * math.sin(2.0 * math.pi * d / 365.0 + math.pi / 4.0),
        ]
        writer.writerow([d] + [f'{v:.12f}' for v in inflows])
