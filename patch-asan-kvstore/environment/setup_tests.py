#!/usr/bin/env python3
"""Create PoC inputs, valid test inputs, expected outputs, and the flawed peer audit for kvstore."""

import json
import os

for d in ['/app/poc', '/app/tests/valid', '/app/tests/expected', '/app/asan_reports']:
    os.makedirs(d, exist_ok=True)

# ---------- PoC inputs (for the 4 ASan-reported vulnerabilities) ----------

# PoC 1: Heap buffer overflow in parse_quoted
# The quoted string "AAAAAAAAAAAAAAAA" (16 A's) between quotes is 18 chars.
# parse_quoted allocates len-2 = 16 bytes for content, but the null
# terminator at index 16 overflows by 1 byte.
with open('/app/poc/poc1.cfg', 'w') as f:
    f.write('SET x "AAAAAAAAAAAAAAAA"\nQUIT\n')

# PoC 2: Use-after-free triggered via cmd_rename then cmd_get
# RENAME transfers the value pointer to the new entry then frees it via
# the old entry. GET on the new key reads freed heap memory.
with open('/app/poc/poc2.cfg', 'w') as f:
    f.write('SET mykey hello_world\nRENAME mykey newkey\nGET newkey\nQUIT\n')

# PoC 3: Stack buffer overflow in cmd_keys
# A pattern longer than PATTERN_BUF (64) overflows the normalised[] buffer
# on the stack during case-normalisation.
with open('/app/poc/poc3.cfg', 'w') as f:
    f.write('SET testkey value\nKEYS ' + 'A' * 200 + '\nQUIT\n')

# PoC 4: Heap buffer over-read in cmd_getrange
# GETRANGE with end=100 on a 3-byte value reads 101 bytes from a 4-byte
# allocation, causing a 97-byte heap over-read.
with open('/app/poc/poc4.cfg', 'w') as f:
    f.write('SET small abc\nGETRANGE small 0 100\nQUIT\n')

# ---------- Valid test inputs and expected outputs ----------

# Valid 1: basic SET, GET, STRLEN, COPY, DEL, EXISTS, APPEND
with open('/app/tests/valid/valid1.cfg', 'w') as f:
    f.write('SET name Alice\n'
            'SET age 30\n'
            'GET name\n'
            'STRLEN name\n'
            'COPY name name2\n'
            'DEL name\n'
            'EXISTS name\n'
            'GET name2\n'
            'APPEND name2 _suffix\n'
            'GET name2\n'
            'QUIT\n')

with open('/app/tests/expected/expected1.txt', 'w') as f:
    f.write('OK\n'
            'OK\n'
            'Alice\n'
            '(5)\n'
            'OK\n'
            '(1)\n'
            '(0)\n'
            'Alice\n'
            'OK\n'
            'Alice_suffix\n')

# Valid 2: RENAME and GETRANGE
with open('/app/tests/valid/valid2.cfg', 'w') as f:
    f.write('SET data abcdef\n'
            'RENAME data newdata\n'
            'GET newdata\n'
            'GETRANGE newdata 1 3\n'
            'GETRANGE newdata 0 5\n'
            'QUIT\n')

with open('/app/tests/expected/expected2.txt', 'w') as f:
    f.write('OK\n'
            'OK\n'
            'abcdef\n'
            '"bcd"\n'
            '"abcdef"\n')

# Valid 3: KEYS pattern matching and DUMP
with open('/app/tests/valid/valid3.cfg', 'w') as f:
    f.write('SET apple 1\n'
            'SET banana 2\n'
            'SET avocado 3\n'
            'KEYS a*\n'
            'DUMP\n'
            'QUIT\n')

with open('/app/tests/expected/expected3.txt', 'w') as f:
    f.write('OK\n'
            'OK\n'
            'OK\n'
            '1) apple\n'
            '2) avocado\n'
            'apple = 1\n'
            'banana = 2\n'
            'avocado = 3\n')

# Valid 4: MGET basic functionality
with open('/app/tests/valid/valid4.cfg', 'w') as f:
    f.write('SET color red\n'
            'SET size large\n'
            'SET shape round\n'
            'MGET color size missing shape\n'
            'QUIT\n')

with open('/app/tests/expected/expected4.txt', 'w') as f:
    f.write('OK\n'
            'OK\n'
            'OK\n'
            '1) red\n'
            '2) large\n'
            '3) (nil)\n'
            '4) round\n')

# ---------- Flawed peer audit (for the solver to evaluate) ----------
# Contains deliberate errors:
# - Entry 1: severity "low" is wrong (heap overflow should be high)
# - Entry 2: function "cmd_get" is wrong (root cause is cmd_rename, cmd_get is crash site)
# - Entry 3: correct
# - Entry 4: CWE-787 (write) is wrong (it's CWE-125, an OOB read); description says "write"
# - Missing: cmd_copy self-copy UAF (no ASan report for this)
# - Missing: cmd_mget stack buffer overflow (no ASan report for this)

peer_audit = {
    "analyst": "prior_review",
    "date": "2024-11-15",
    "vulnerabilities": [
        {
            "id": 1,
            "cwe_id": "CWE-122",
            "function": "parse_quoted",
            "severity": "low",
            "description": (
                "Off-by-one in malloc allocation for quoted string parsing. "
                "malloc(len-2) should account for the null terminator byte. "
                "The terminating null write overflows the allocation by one byte."
            )
        },
        {
            "id": 2,
            "cwe_id": "CWE-416",
            "function": "cmd_get",
            "severity": "critical",
            "description": (
                "Use-after-free when accessing value of a renamed key. "
                "The GET handler reads from a freed heap allocation after "
                "RENAME transfers and frees the value pointer."
            )
        },
        {
            "id": 3,
            "cwe_id": "CWE-121",
            "function": "cmd_keys",
            "severity": "high",
            "description": (
                "Stack buffer overflow in pattern normalization. User-supplied "
                "pattern is copied into a fixed 64-byte stack buffer without "
                "bounds checking during case-insensitive conversion."
            )
        },
        {
            "id": 4,
            "cwe_id": "CWE-787",
            "function": "cmd_getrange",
            "severity": "high",
            "description": (
                "Heap buffer overflow write in GETRANGE when end index exceeds "
                "the stored value length, causing memcpy to write beyond the "
                "allocated output buffer."
            )
        }
    ]
}

with open('/app/peer_audit.json', 'w') as f:
    json.dump(peer_audit, f, indent=2)

print("Test fixtures and peer audit created successfully.")
