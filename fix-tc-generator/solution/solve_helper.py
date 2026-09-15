#!/usr/bin/env python3
"""
Fix all bugs in tc_generator.py and run it to produce correct output.

Bug 1: dscp_to_tos() returns the raw DSCP value instead of shifting left by 2.
       DSCP occupies bits [7:2] of the TOS byte, so TOS = DSCP << 2.

Bug 2: generate_class_commands() sets child class parent to cls['parent_minor']
       (the grandparent / root) instead of cls['classid_minor'] (the actual parent).

Bug 3: generate_filter_commands() uses TOS mask 0xff which matches all 8 bits
       including the 2 ECN bits. Must use 0xfc to match only the 6 DSCP bits.

Bug 4: generate_filter_commands() and generate_report() use child.get('dscp')
       as a truthiness check. DSCP 0 (Best Effort) is a valid value but falsy
       in Python, so the filter for the default class is silently skipped.
"""
import subprocess

with open('/app/tc_generator.py') as f:
    code = f.read()

# Fix 1: dscp_to_tos must left-shift by 2
code = code.replace(
    '    return dscp_value\n',
    '    return dscp_value << 2\n',
    1
)

# Fix 2: child parent must reference the parent class, not root
code = code.replace(
    """child_parent = f"{handle}:{cls['parent_minor']}\"""",
    """child_parent = f"{handle}:{cls['classid_minor']}\""""
)

# Fix 3: filter mask must be 0xfc to exclude ECN bits
code = code.replace('0xff flowid', '0xfc flowid')

# Fix 4: DSCP 0 is falsy - use 'in' check instead of truthiness
code = code.replace(
    "if child.get('dscp'):",
    "if 'dscp' in child:"
)

with open('/app/tc_generator.py', 'w') as f:
    f.write(code)

# Run the fixed generator
result = subprocess.run(
    ['python3', '/app/tc_generator.py'],
    capture_output=True, text=True, cwd='/app'
)
print(result.stdout)
if result.stderr:
    print(result.stderr)
if result.returncode != 0:
    raise SystemExit(f"Generator failed with exit code {result.returncode}")
