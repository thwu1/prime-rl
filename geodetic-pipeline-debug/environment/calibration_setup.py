#!/usr/bin/env python3
"""Generate random calibration data for geodetic pipeline debugging task.

Each Docker build produces a unique task_instance_id and random coordinate
pairs within valid projection zones, ensuring the agent must actually use
PROJ tools to compute results.
"""
import json
import os
import random
import secrets

random.seed(secrets.token_bytes(32))

token = secrets.token_hex(16)

coordinates = [
    {
        "projection_id": 1,
        "projection_name": "sterea",
        "description": "Oblique Stereographic (Netherlands RD New)",
        "longitude": round(random.uniform(3.5, 7.0), 6),
        "latitude": round(random.uniform(50.5, 53.5), 6),
    },
    {
        "projection_id": 2,
        "projection_name": "poly",
        "description": "American Polyconic (Brazil SIRGAS 2000)",
        "longitude": round(random.uniform(-60.0, -40.0), 6),
        "latitude": round(random.uniform(-25.0, -5.0), 6),
    },
    {
        "projection_id": 3,
        "projection_name": "aea",
        "description": "Albers Equal Area Conic (Australian Albers)",
        "longitude": round(random.uniform(120.0, 150.0), 6),
        "latitude": round(random.uniform(-40.0, -15.0), 6),
    },
    {
        "projection_id": 4,
        "projection_name": "omerc",
        "description": "Hotine Oblique Mercator (East Malaysia BRSO)",
        "longitude": round(random.uniform(110.0, 118.0), 6),
        "latitude": round(random.uniform(1.0, 7.0), 6),
    },
    {
        "projection_id": 5,
        "projection_name": "geocent",
        "description": "Geocentric (WGS 84)",
        "longitude": round(random.uniform(-170.0, 170.0), 6),
        "latitude": round(random.uniform(-70.0, 70.0), 6),
        "height": round(random.uniform(10.0, 3000.0), 2),
    },
]

data = {
    "task_instance_id": token,
    "coordinates": coordinates,
}

os.makedirs("/app", exist_ok=True)
with open("/app/calibration_data.json", "w") as f:
    json.dump(data, f, indent=2)
