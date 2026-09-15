#!/usr/bin/env python3

"""Generate the vulnerability assessment bug report."""

import json

bug_report = [
    {
        "primitive": "salsa20",
        "description": "Salsa20 quarter-round uses rotation constant 14 instead of the correct 13, producing wrong keystream output",
        "security_impact": "encryption_failure",
        "exploitability": "passive_failure"
    },
    {
        "primitive": "salsa20",
        "description": "Sigma constant uses uppercase 'K' instead of lowercase 'k' in the string 'expand 32-byte k', breaking interoperability with all correct NaCl implementations",
        "security_impact": "interop_failure",
        "exploitability": "passive_failure"
    },
    {
        "primitive": "poly1305",
        "description": "Poly1305 key clamping uses r[11]&=63 instead of r[11]&=15, allowing 2 extra bits in the secret polynomial evaluation point r, weakening the MAC security bound and enabling authentication bypass",
        "security_impact": "authentication_bypass",
        "exploitability": "actively_exploitable"
    },
    {
        "primitive": "curve25519",
        "description": "Field inversion inv25519 skips multiplication at bit position 3 instead of 4, computing x^(2^255-25) instead of x^(2^255-21) = x^(p-2), yielding incorrect shared secrets",
        "security_impact": "key_exchange_failure",
        "exploitability": "passive_failure"
    }
]

with open("/app/bug_report.json", "w") as f:
    json.dump(bug_report, f, indent=2)

print("Bug report written to /app/bug_report.json")
