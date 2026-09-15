#!/usr/bin/env python3
"""Generate results.json using the ctypes bridge to libperft960.so."""


import json
import sys

sys.path.insert(0, '/app')
from perft_bridge import run_perft

positions = {
    "pos1": {"fen": "nrkbbqrn/pppppppp/8/8/8/8/PPPPPPPP/NRKBBQRN w BGbg - 0 1", "depth": 4},
    "pos2": {"fen": "rbbkrqnn/pppppppp/8/8/8/8/PPPPPPPP/RBBKRQNN w AEae - 0 1", "depth": 4},
    "pos3": {"fen": "qnrbbnkr/pppppppp/8/8/8/8/PPPPPPPP/QNRBBNKR w HChc - 0 1", "depth": 4},
}

results = {}
for pos_name, info in positions.items():
    stats = run_perft(info["fen"], info["depth"])
    results[pos_name] = {**info, **stats}
    print(f"{pos_name}: {stats['nodes']} nodes")

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Results written to /app/results.json")
