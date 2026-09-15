"""
Parse TLC output and write /app/results.json with run statistics.
"""
import json
import re
import sys

with open("/tmp/tlc_output.txt", "r") as f:
    output = f.read()

distinct_match = re.search(r"([\d,]+) distinct states found", output)
total_match = re.search(r"([\d,]+) states generated", output)
depth_match = re.search(r"depth of the complete state graph search is (\d+)", output)

if not distinct_match or not total_match or not depth_match:
    print("ERROR: Could not parse TLC output for state statistics")
    print(output[-2000:])
    sys.exit(1)

results = {
    "distinct_states": int(distinct_match.group(1).replace(",", "")),
    "total_states": int(total_match.group(1).replace(",", "")),
    "state_depth": int(depth_match.group(1)),
}

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"Results written: {results}")
