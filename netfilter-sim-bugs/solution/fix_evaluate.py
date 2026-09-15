#!/usr/bin/env python3
"""
Fix the incomplete match functions in /app/evaluate.py.

Two match types are stubbed with NotImplementedError:
  1. CIDR subnet matching (src_network)
  2. Payload length comparison (min_payload_length)
"""

import sys


def apply_fixes():
    with open("/app/evaluate.py") as f:
        code = f.read()

    original = code

    # Fix 1: Implement CIDR subnet matching
    old_cidr = (
        '    if "src_network" in rule_match:\n'
        '        # TODO: Implement CIDR subnet matching using the ipaddress module.\n'
        '        # Check whether packet.src_ip falls within the network specified\n'
        '        # by rule_match["src_network"] (e.g., "198.18.0.0/15").\n'
        '        # Return False if the packet\'s source IP is NOT in the network.\n'
        '        raise NotImplementedError(\n'
        '            "CIDR subnet matching not yet implemented. "\n'
        '            "Use ipaddress.ip_address() and ipaddress.ip_network() "\n'
        '            "to check if packet.src_ip is within rule_match[\'src_network\']."\n'
        '        )'
    )
    new_cidr = (
        '    if "src_network" in rule_match:\n'
        '        if ip_address(packet.src_ip) not in ip_network(\n'
        '                rule_match["src_network"], strict=False):\n'
        '            return False'
    )
    code = code.replace(old_cidr, new_cidr)

    # Fix 2: Implement payload length comparison
    old_payload = (
        '    if "min_payload_length" in rule_match:\n'
        '        # TODO: Implement payload length comparison.\n'
        '        # Check whether packet.payload_length is strictly greater than\n'
        '        # the value specified in rule_match["min_payload_length"].\n'
        '        # Return False if the payload is NOT larger than the threshold.\n'
        '        raise NotImplementedError(\n'
        '            "Payload length matching not yet implemented. "\n'
        '            "Compare packet.payload_length against "\n'
        '            "rule_match[\'min_payload_length\']."\n'
        '        )'
    )
    new_payload = (
        '    if "min_payload_length" in rule_match:\n'
        '        if packet.payload_length <= rule_match["min_payload_length"]:\n'
        '            return False'
    )
    code = code.replace(old_payload, new_payload)

    if code == original:
        print("ERROR: No changes applied to evaluate.py", file=sys.stderr)
        sys.exit(1)

    with open("/app/evaluate.py", "w") as f:
        f.write(code)

    print("Fixed evaluate.py:")
    print("  1. CIDR subnet matching (src_network)")
    print("  2. Payload length comparison (min_payload_length)")


if __name__ == "__main__":
    apply_fixes()
