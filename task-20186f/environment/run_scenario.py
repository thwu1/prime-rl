#!/usr/bin/env python3
"""Run a Kafka KIP-966 replication protocol simulation scenario."""
import json
import sys

def main():
    if len(sys.argv) != 2:
        print("Usage: run_scenario.py <scenario.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        scenario = json.load(f)

    from simulator import PartitionSimulator

    sim = PartitionSimulator(scenario["config"])
    for event in scenario["events"]:
        sim.process_event(event)

    result = sim.get_result()
    print(json.dumps(result.to_dict(), indent=2))

if __name__ == "__main__":
    main()
