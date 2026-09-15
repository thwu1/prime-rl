#!/usr/bin/env python3
"""Fix the broken .coveragerc configuration.

Bugs in the original:
1. source = /opt/project/calclib  -> wrong path, should be 'calclib'
2. omit includes *batch* -> incorrectly excludes batch.py from measurement
3. branch = True is in [report] not [run] -> branch coverage not actually enabled
4. Missing parallel = True in [run] -> needed for multiprocessing data files
5. Missing concurrency = multiprocessing in [run] -> workers not traced
6. Missing dynamic_context = test_function in [run] -> no per-test context tracking
7. exclude_lines has 'raise ValueError' and 'raise TypeError' -> masks real code paths
"""

FIXED_CONFIG = """\
[run]
branch = True
source = calclib
dynamic_context = test_function
concurrency = multiprocessing
parallel = True

[report]
show_missing = True
exclude_lines =
    pragma: no cover
    if __name__ == .__main__.

[html]
directory = htmlcov
"""

with open("/app/.coveragerc", "w") as f:
    f.write(FIXED_CONFIG)

print("Fixed .coveragerc — corrected 7 configuration bugs")
