#!/usr/bin/env python3
"""Fix the best parser (gamma) to create a fully conformant implementation.

Parser gamma's only defect is a too-small buffer (22 bytes) in the strtod()
slow path, which causes snprintf truncation for inputs with long mantissas
and large-magnitude exponents. Enlarging the buffer to 64 bytes fixes it.
"""

import os

SRC = '/app/parsers/parser_gamma.c'
DST = '/app/src/conformant.c'

os.makedirs('/app/src', exist_ok=True)

with open(SRC) as f:
    code = f.read()

# Fix: enlarge the slow-path buffer from 22 to 64 bytes
old = '        char buf[24];  /* compact buffer for strtod reconstruction */'
new = '        char buf[64];  /* buffer for strtod reconstruction */'

assert old in code, f"Expected pattern not found in {SRC}"
code = code.replace(old, new)

with open(DST, 'w') as f:
    f.write(code)

print(f"Fixed: {SRC} -> {DST} (enlarged slow-path buffer 22 -> 64)")
