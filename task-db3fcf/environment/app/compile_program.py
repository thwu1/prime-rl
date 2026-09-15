#!/usr/bin/env python3
"""Compile a MiniCalc source file to bytecode JSON."""
import sys
import json

sys.path.insert(0, "/opt/minicalc")
from compiler import compile_source

if len(sys.argv) != 3:
    print("Usage: python3 compile_program.py <input.mc> <output.json>", file=sys.stderr)
    sys.exit(1)

with open(sys.argv[1]) as f:
    source = f.read()

bytecode = compile_source(source)
with open(sys.argv[2], "w") as f:
    json.dump(bytecode, f, indent=2)
