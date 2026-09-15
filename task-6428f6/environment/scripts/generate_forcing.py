#!/usr/bin/env python3
"""Generate per-catchment forcing CSV files for ngen from catchment GeoJSON."""
import json
import csv
import os
from datetime import datetime, timedelta

with open('/tmp/catchments.geojson') as f:
    data = json.load(f)

cat_ids = [feat['id'] for feat in data['features']]

forcing_dir = '/app/data/forcing'
os.makedirs(forcing_dir, exist_ok=True)

columns = [
    'time', 'APCP_surface', 'DLWRF_surface', 'DSWRF_surface',
    'PRES_surface', 'SPFH_2maboveground', 'TMP_2maboveground',
    'UGRD_10maboveground', 'VGRD_10maboveground', 'precip_rate'
]

start = datetime(2015, 12, 1)
for cid in cat_ids:
    filepath = os.path.join(forcing_dir, f'{cid}_forcing.csv')
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for h in range(24):
            t = start + timedelta(hours=h)
            row = [
                t.strftime('%Y-%m-%d %H:%M:%S'),
                0.0,
                350.0 + h * 0.5,
                max(0.0, 400.0 * (1.0 - abs(h - 12) / 12.0)),
                101300.0,
                0.008,
                280.0 + 5.0 * (1.0 - abs(h - 14) / 14.0),
                -2.0,
                1.0,
                0.0 if h < 6 or h > 20 else 0.001
            ]
            writer.writerow(row)
