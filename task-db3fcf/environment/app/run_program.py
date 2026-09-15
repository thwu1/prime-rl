#!/usr/bin/env python3
"""Run a MiniCalc bytecode JSON file through the VM."""
import sys
import json

sys.path.insert(0, "/opt/minicalc")
from vm import run_bytecode

if len(sys.argv) != 2:
    print("Usage: python3 run_program.py <bytecode.json>", file=sys.stderr)
    sys.exit(1)

with open(sys.argv[1]) as f:
    bytecode = json.load(f)

output = run_bytecode(bytecode)
print(output, end="")
