#!/usr/bin/env python3
"""Fix bugs in the TTCN-3 template matching engine.

Reads the buggy matcher at /app/matcher.py, diagnoses and fixes all
semantic bugs, and writes the corrected version back.

"""

import subprocess

with open("/app/matcher.py", "r") as f:
    code = f.read()

# Fix 1: Range must reject booleans.
# Python's isinstance(True, int) is True, so booleans slip through the
# numeric type check. TTCN-3 ranges operate on numeric protocol values,
# not truth values.
code = code.replace(
    "def _match_range(lo, hi, value):\n"
    "    if value is None:\n"
    "        return False\n"
    "    if not isinstance(value, (int, float)):\n"
    "        return False",
    "def _match_range(lo, hi, value):\n"
    "    if value is None or isinstance(value, bool):\n"
    "        return False\n"
    "    if not isinstance(value, (int, float)):\n"
    "        return False"
)

# Fix 2: Complement must reject absent/None values.
# Per TTCN-3 semantics, complement requires a present value to test
# against the exclusion list. None/absent should always fail.
code = code.replace(
    "def _match_complement(templates, value, registry):\n"
    "    return not any(match(ct, value, registry) for ct in templates)",
    "def _match_complement(templates, value, registry):\n"
    "    if value is None:\n"
    "        return False\n"
    "    return not any(match(ct, value, registry) for ct in templates)"
)

# Fix 3: Star pattern must match zero-length strings.
# TTCN-3 '*' means zero or more characters. The buggy code used '.+'
# (one or more) instead of '.*' (zero or more).
code = code.replace(
    "        elif c == '*':\n"
    "            result.append('.+')",
    "        elif c == '*':\n"
    "            result.append('.*')"
)

# Fix 4: List backtracking must try all consumption lengths.
# AnyOrNone (*) in record-of context must try consuming 0, 1, 2, ..., N
# elements. The buggy code only tried 0 and all, missing intermediate
# split points needed for patterns like [*, X, *].
code = code.replace(
    "        for end in [vi, len(value)]:",
    "        for end in range(vi, len(value) + 1):"
)

# Fix 5: Template modification must use deep copy.
# Shallow copy causes field spec mutations to leak to the base template
# in the registry, corrupting it for subsequent test cases.
code = code.replace(
    "    result = copy.copy(base)\n"
    "    result[\"fields\"] = dict(result[\"fields\"])",
    "    result = copy.deepcopy(base)"
)

# Fix 6: Component creation must be idempotent.
# Re-creating an existing component must not reset its accumulated
# verdict, as component identity is immutable in TTCN-3.
code = code.replace(
    "    def create_component(self, component_id):\n"
    "        \"\"\"Create a test component with initial verdict 'none'.\"\"\"\n"
    "        self.components[component_id] = 0",
    "    def create_component(self, component_id):\n"
    "        \"\"\"Create a test component with initial verdict 'none'.\"\"\"\n"
    "        if component_id not in self.components:\n"
    "            self.components[component_id] = 0"
)

with open("/app/matcher.py", "w") as f:
    f.write(code)

# Verify by running the conformance runner
result = subprocess.run(
    ["python3", "/app/conformance_runner.py"],
    capture_output=True, text=True, cwd="/app"
)
print(result.stdout)
if result.returncode != 0:
    print("STDERR:", result.stderr)
    exit(1)
