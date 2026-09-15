"""
System configuration for the dirty page write throttling simulation.

Models a system with two backing devices (SSD and HDD) and five writer
tasks generating dirty pages at different rates.
"""

CONFIG = {
    "system": {
        "total_pages": 10000,
        "dirty_limit_ratio": 0.4,       # Hard limit = 4000 pages
        "setpoint_ratio": 0.6,          # Setpoint = 60% of limit = 2400 pages
        "period_ms": 100.0,             # Throttle period in milliseconds
    },
    "simulation": {
        "num_ticks": 1000,
    },
    "bdis": [
        {"name": "ssd", "bandwidth": 100.0},   # Fast device: 100 pages/tick
        {"name": "hdd", "bandwidth": 20.0},     # Slow device: 20 pages/tick
    ],
    "tasks": [
        {"name": "writer-1", "bdi": "ssd", "write_rate": 50.0},
        {"name": "writer-2", "bdi": "ssd", "write_rate": 45.0},
        {"name": "writer-3", "bdi": "ssd", "write_rate": 40.0},
        {"name": "writer-4", "bdi": "hdd", "write_rate": 25.0},
        {"name": "writer-5", "bdi": "hdd", "write_rate": 20.0},
    ],
}
