#!/usr/bin/env python3
"""Generate a lit-based test suite at /app/lit_suite/.

Creates:
  - lit.cfg.py: lit configuration with ShTest format and %FileCheck substitution
  - One .test file per manifest test case with appropriate RUN: directives
"""

import os
import json

SUITE_DIR = "/app/lit_suite"
os.makedirs(SUITE_DIR, exist_ok=True)

# Read manifest to generate test files
with open("/app/manifest.json") as f:
    manifest = json.load(f)

# Write lit.cfg.py
# Key: ShTest() uses the internal shell (execute_external=False by default)
# which provides the 'not' builtin for expected-failure tests.
# ShTest(True) would require an external 'not' binary which we don't have.
lit_cfg = """\
import lit.formats
import os

config.name = 'FileCheck-Conformance'
config.test_format = lit.formats.ShTest()
config.suffixes = ['.test']
config.test_source_root = os.path.dirname(os.path.abspath(__file__))
config.test_exec_root = config.test_source_root

# Substitution for the FileCheck clone under test
config.substitutions.append(('%FileCheck', 'python3 /app/filecheck.py'))
"""

with open(f"{SUITE_DIR}/lit.cfg.py", "w") as f:
    f.write(lit_cfg)

# Generate one .test file per manifest test case
test_count = 0
for tc in manifest["test_cases"]:
    name = tc["name"]
    check = tc["check_file"]
    inp = tc["input_file"]
    expected = tc["expected"]
    flags = tc.get("flags", [])

    flags_str = " ".join(flags) if flags else ""
    cmd = f"%FileCheck /app/test_inputs/{check} --input-file /app/test_inputs/{inp}"
    if flags_str:
        cmd += f" {flags_str}"

    if expected == "fail":
        run_line = f"# RUN: not {cmd}"
    else:
        run_line = f"# RUN: {cmd}"

    with open(f"{SUITE_DIR}/{name}.test", "w") as f:
        f.write(f"# Test: {name} (expected: {expected})\n")
        f.write(f"{run_line}\n")

    test_count += 1

print(f"Created lit suite at {SUITE_DIR} with {test_count} tests")
print(f"  lit.cfg.py: ShTest format with %FileCheck substitution")
print(f"  {test_count} .test files with RUN: directives")
