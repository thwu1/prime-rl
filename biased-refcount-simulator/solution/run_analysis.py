"""
Driver script: processes all BRC scenarios and writes results.json.
"""


import json
import os
import sys

sys.path.insert(0, "/app")
from brc_engine import BRCSimulator

SCENARIO_DIR = "/app/scenarios"
OUTPUT_PATH = "/app/results.json"


def main():
    all_results = {}

    scenario_files = sorted(f for f in os.listdir(SCENARIO_DIR) if f.endswith(".json"))
    for fname in scenario_files:
        scenario_name = fname.replace(".json", "")
        path = os.path.join(SCENARIO_DIR, fname)

        with open(path) as f:
            scenario = json.load(f)

        sim = BRCSimulator()
        results = sim.run_scenario(scenario["operations"])
        all_results[scenario_name] = results

    with open(OUTPUT_PATH, "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"Wrote results for {len(all_results)} scenarios to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
