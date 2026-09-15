#!/usr/bin/env python3
"""Generate the topology.json test scenario."""
import json

topology = {
    "nodes": ["A", "B", "C", "D", "E", "F", "G"],
    "initial_links": [
        {"src": "A", "dst": "B", "cost": 1},
        {"src": "B", "dst": "C", "cost": 3},
        {"src": "A", "dst": "D", "cost": 2},
        {"src": "B", "dst": "E", "cost": 4},
        {"src": "C", "dst": "F", "cost": 1},
        {"src": "D", "dst": "E", "cost": 2},
        {"src": "E", "dst": "F", "cost": 1},
        {"src": "F", "dst": "G", "cost": 3}
    ],
    "events": [
        {"type": "update", "src": "A", "dst": "B", "cost": 5},
        {"type": "update", "src": "D", "dst": "E", "cost": 1},
        {"type": "crash", "node": "G"},
        {"type": "update", "src": "C", "dst": "F", "cost": 4},
        {"type": "revive", "node": "G"},
        {"type": "update", "src": "F", "dst": "G", "cost": 1},
        {"type": "crash", "node": "E"},
        {"type": "update", "src": "B", "dst": "E", "cost": 9999}
    ]
}

with open("/app/topology.json", "w") as f:
    json.dump(topology, f, indent=2)
