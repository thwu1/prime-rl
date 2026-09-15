"""Generate all N-Queens Completion instance files at Docker build time."""
import json
import os

INSTANCES = {
    "instance_01": {"n": 10, "pre_placed": [[0, 0], [3, 7], [7, 1]]},
    "instance_02": {"n": 15, "pre_placed": [[0, 3], [4, 11], [8, 6], [12, 14]]},
    "instance_03": {"n": 25, "pre_placed": [[0, 1], [5, 11], [10, 21], [15, 6], [20, 16], [24, 24]]},
    "instance_04": {"n": 50, "pre_placed": [[0, 1], [10, 21], [20, 41], [30, 12], [40, 32], [49, 4]]},
    "instance_05": {"n": 80, "pre_placed": [[0, 1], [16, 33], [32, 65], [48, 18], [64, 50], [79, 4]]},
    "instance_06": {"n": 60, "pre_placed": [[0, 1], [3, 7], [6, 13], [9, 19], [12, 25], [15, 31], [18, 37], [21, 43], [24, 49], [27, 55], [30, 0], [33, 6], [36, 12], [39, 18], [42, 24], [45, 30], [48, 36], [51, 42], [54, 48], [57, 54]]},
    "instance_07": {"n": 8, "pre_placed": [[0, 2], [2, 5], [4, 1], [6, 4]]},
    "instance_08": {"n": 10, "pre_placed": [[0, 1], [2, 4], [4, 7], [6, 2], [8, 5]]},
    "instance_09": {"n": 12, "pre_placed": [[0, 0], [1, 2], [2, 4], [3, 7], [4, 9], [5, 11], [6, 5], [7, 1]]},
    "instance_10": {"n": 100, "pre_placed": [[0, 1], [20, 41], [40, 81], [60, 20], [80, 60], [99, 98]]},
    "instance_11": {"n": 5, "pre_placed": []},
    "count_01": {"n": 8, "pre_placed": [], "count_solutions": True},
    "count_02": {"n": 10, "pre_placed": [[4, 2]], "count_solutions": True},
    "count_03": {"n": 12, "pre_placed": [[0, 3], [5, 9]], "count_solutions": True},
    "count_04": {"n": 9, "pre_placed": [[3, 7], [4, 1], [8, 4]], "count_solutions": True},
}

os.makedirs("/app/instances", exist_ok=True)
for name, data in INSTANCES.items():
    with open(f"/app/instances/{name}.json", "w") as f:
        json.dump(data, f)
    print(f"  Created {name}.json")

print(f"Generated {len(INSTANCES)} instance files in /app/instances/")
