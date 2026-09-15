#!/usr/bin/env python3
"""Fix the 5 bugs in /app/.coveragerc."""

FIXED_CONFIG = """\
[run]
source = src
dynamic_context = test_function
branch = true
omit =
    */tests/*
    */__pycache__/*

[report]
show_missing = true
exclude_lines =
    pragma: no cover
    if __name__

[json]
output = coverage.json
pretty_print = true
show_contexts = true
"""

with open('/app/.coveragerc', 'w') as f:
    f.write(FIXED_CONFIG)

print("Fixed .coveragerc: 5 bugs corrected")
print("  1. source: lib -> src")
print("  2. dynamic_context: test_name -> test_function")
print("  3. Added: branch = true")
print("  4. Removed: raise\\s from exclude_lines")
print("  5. Added: show_contexts = true to [json]")
