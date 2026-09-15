#!/usr/bin/env python3
"""Legitimate query test suite.

These queries represent normal, non-malicious usage of the query interface
and MUST be allowed by both the original and any patched version of the WAF.
"""

import sys

LEGITIMATE_QUERIES = [
    "username = 'admin'",
    "department = 'Engineering'",
    "role = 'user' AND department = 'Engineering'",
    "id >= 2",
    "id < 10",
    "username LIKE 'a%'",
    "email = 'jdoe@corp.local'",
    "id BETWEEN 1 AND 3",
    "department IN ('IT', 'HR')",
    "role != 'admin'",
    "username = 'admin' AND role = 'admin'",
    "id = 1",
]

if __name__ == '__main__':
    from waf import WAF
    waf = WAF()
    passed = 0
    failed = 0
    for query in LEGITIMATE_QUERIES:
        allowed, triggered = waf.check(query)
        if allowed:
            print(f"  [PASS] {query}")
            passed += 1
        else:
            rules = ', '.join(r[0] for r in triggered)
            print(f"  [FAIL] {query} (blocked by: {rules})")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
