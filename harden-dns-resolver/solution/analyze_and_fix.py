#!/usr/bin/env python3
"""
Analyze the DNS resolver for security vulnerabilities, protocol violations,
and missing features. Apply all fixes and write a structured audit report.
"""

import json
import re
import sys

RESOLVER_PATH = "/app/resolver.py"
AUDIT_PATH = "/app/audit.json"


def normalize(text):
    """Strip trailing whitespace from each line for robust matching."""
    return "\n".join(line.rstrip() for line in text.split("\n"))


def apply_fix(code, old, new, label):
    """Replace exact pattern in code, with whitespace-normalized fallback."""
    if old in code:
        print(f"  Applied '{label}' (exact match)")
        return code.replace(old, new, 1)
    # Try with normalized whitespace
    old_n = normalize(old)
    new_n = normalize(new)
    if old_n in code:
        print(f"  Applied '{label}' (normalized match)")
        return code.replace(old_n, new_n, 1)
    print(f"  WARNING: pattern for '{label}' not found — may be already fixed",
          file=sys.stderr)
    return code


def replace_send_query_regex(code):
    """Robust regex-based replacement of the entire send_query function.
    Used as a fallback when exact string matching fails."""
    new_func = (
        'def send_query(server: str, name: str, type_: int = TYPE_A,\n'
        '               timeout: float = 5.0) -> DNSPacket:\n'
        '    query = build_query(name, type_)\n'
        '    query_id = struct.unpack("!H", query[:2])[0]\n'
        '    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n'
        '    sock.settimeout(timeout)\n'
        '    try:\n'
        '        sock.sendto(query, (server, 53))\n'
        '        while True:\n'
        '            data, _ = sock.recvfrom(4096)\n'
        '            response = parse_dns_packet(data)\n'
        '            if response.header.id == query_id:\n'
        '                return response\n'
        '    finally:\n'
        '        sock.close()'
    )
    # Match from 'def send_query(' through 'sock.close()'
    pattern = r'def send_query\(server: str.*?sock\.close\(\)'
    result, count = re.subn(pattern, new_func, code, count=1, flags=re.DOTALL)
    if count > 0:
        print("  Applied send_query fix via regex fallback")
    else:
        print("  CRITICAL: Could not apply send_query fix", file=sys.stderr)
    return result


def main():
    with open(RESOLVER_PATH) as f:
        code = f.read()

    # Normalize trailing whitespace for reliable matching
    code = normalize(code)

    # ------------------------------------------------------------------
    # Fix 1: Compression pointer loop detection
    # Add visited-offset tracking to decode_dns_name so circular
    # pointers raise ValueError instead of infinite-looping.
    # ------------------------------------------------------------------
    code = apply_fix(
        code,
        "def decode_dns_name(data: bytes, offset: int) -> Tuple[str, int]:\n"
        "    parts = []\n"
        "    jumped = False\n"
        "    return_offset = offset",

        "def decode_dns_name(data: bytes, offset: int, _visited=None) -> Tuple[str, int]:\n"
        "    if _visited is None:\n"
        "        _visited = set()\n"
        "    parts = []\n"
        "    jumped = False\n"
        "    return_offset = offset",
        "compression-loop: add _visited param",
    )

    code = apply_fix(
        code,
        "            pointer = struct.unpack(\"!H\", data[offset:offset + 2])[0] & 0x3FFF\n"
        "            offset = pointer\n"
        "            continue",

        "            pointer = struct.unpack(\"!H\", data[offset:offset + 2])[0] & 0x3FFF\n"
        "            if pointer in _visited:\n"
        "                raise ValueError(\"Compression pointer loop detected\")\n"
        "            _visited.add(pointer)\n"
        "            offset = pointer\n"
        "            continue",
        "compression-loop: detect cycle",
    )

    # ------------------------------------------------------------------
    # Fix 2: Follow CNAME records during resolution
    # After checking for a direct A answer, detect CNAME records
    # and recursively resolve the CNAME target.
    # ------------------------------------------------------------------
    code = apply_fix(
        code,
        "        # Look for NS delegation",

        "        # Follow CNAME if present in answers\n"
        "        for rec in response.answers:\n"
        "            if rec.type_ == TYPE_CNAME and rec.name.lower().rstrip(\".\") == name.lower().rstrip(\".\"):\n"
        "                return resolve(rec.data, type_, _depth + 1)\n"
        "\n"
        "        # Look for NS delegation",
        "cname: follow CNAME records",
    )

    # ------------------------------------------------------------------
    # Fix 3: Resolve NS hostname when no glue record is available
    # Instead of returning None, recursively resolve the NS name.
    # ------------------------------------------------------------------
    code = apply_fix(
        code,
        "        if glue is not None:\n"
        "            nameserver = glue\n"
        "        else:\n"
        "            return None",

        "        if glue is not None:\n"
        "            nameserver = glue\n"
        "        else:\n"
        "            ns_ip = resolve(ns_name, TYPE_A, _depth + 1)\n"
        "            if ns_ip is None:\n"
        "                return None\n"
        "            nameserver = ns_ip",
        "ns-glue: resolve NS hostname",
    )

    # ------------------------------------------------------------------
    # Fix 4: Add EDNS0 OPT record to queries
    # Append an OPT pseudo-record (type 41) with UDP payload size 4096.
    # ------------------------------------------------------------------
    code = apply_fix(
        code,
        "    header = struct.pack(\"!HHHHHH\", txn_id, flags, 1, 0, 0, 0)\n"
        "    question = encode_dns_name(name) + struct.pack(\"!HH\", type_, CLASS_IN)\n"
        "    return header + question",

        "    header = struct.pack(\"!HHHHHH\", txn_id, flags, 1, 0, 0, 1)\n"
        "    question = encode_dns_name(name) + struct.pack(\"!HH\", type_, CLASS_IN)\n"
        "    # EDNS0 OPT pseudo-record: name=root, type=OPT(41), class=UDP-size,\n"
        "    # ttl=extended-rcode+flags, rdlength=0\n"
        "    opt = b\"\\x00\" + struct.pack(\"!HHIH\", TYPE_OPT, 4096, 0, 0)\n"
        "    return header + question + opt",
        "edns0: add OPT record",
    )

    # ------------------------------------------------------------------
    # Fix 5 + 6: Increase recv buffer AND add transaction ID verification
    # The recv buffer of 512 is insufficient for EDNS0-sized responses.
    # Also, the response's transaction ID must match the query's to
    # prevent DNS cache poisoning attacks.
    #
    # Uses exact match first, then regex fallback for robustness.
    # ------------------------------------------------------------------
    old_sq = (
        "def send_query(server: str, name: str, type_: int = TYPE_A,\n"
        "               timeout: float = 5.0) -> DNSPacket:\n"
        "    query = build_query(name, type_)\n"
        "    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        "    sock.settimeout(timeout)\n"
        "    try:\n"
        "        sock.sendto(query, (server, 53))\n"
        "        data, _ = sock.recvfrom(512)\n"
        "        return parse_dns_packet(data)\n"
        "    finally:\n"
        "        sock.close()"
    )
    new_sq = (
        "def send_query(server: str, name: str, type_: int = TYPE_A,\n"
        "               timeout: float = 5.0) -> DNSPacket:\n"
        "    query = build_query(name, type_)\n"
        "    query_id = struct.unpack(\"!H\", query[:2])[0]\n"
        "    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        "    sock.settimeout(timeout)\n"
        "    try:\n"
        "        sock.sendto(query, (server, 53))\n"
        "        while True:\n"
        "            data, _ = sock.recvfrom(4096)\n"
        "            response = parse_dns_packet(data)\n"
        "            if response.header.id == query_id:\n"
        "                return response\n"
        "    finally:\n"
        "        sock.close()"
    )

    if old_sq in code:
        code = code.replace(old_sq, new_sq, 1)
        print("  Applied send_query fix (exact match)")
    elif normalize(old_sq) in code:
        code = code.replace(normalize(old_sq), normalize(new_sq), 1)
        print("  Applied send_query fix (normalized match)")
    else:
        # Regex fallback: find and replace the entire send_query function
        code = replace_send_query_regex(code)

    with open(RESOLVER_PATH, "w") as f:
        f.write(code)

    # ------------------------------------------------------------------
    # Verify all fixes were applied
    # ------------------------------------------------------------------
    checks = {
        "compression loop detection": "_visited" in code,
        "CNAME following": "TYPE_CNAME" in code and "resolve(rec.data" in code,
        "glueless NS resolution": "resolve(ns_name" in code,
        "EDNS0 OPT record": "TYPE_OPT, 4096" in code,
        "recv buffer >= 4096": "recvfrom(4096)" in code,
        "transaction ID check": "query_id" in code and "response.header.id == query_id" in code,
    }
    all_ok = all(checks.values())
    print("\nVerification:")
    for check_name, ok in checks.items():
        status = "OK" if ok else "MISSING"
        print(f"  [{status}] {check_name}")

    if all_ok:
        print("All six fixes verified in resolver.py")
    else:
        print("WARNING: Some fixes may not have been applied", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Write structured audit report
    # ------------------------------------------------------------------
    audit = {
        "findings": [
            {
                "id": "compression-pointer-loop",
                "category": "vulnerability",
                "severity": "critical",
                "description": (
                    "DNS name decoder has no cycle detection for compression "
                    "pointers, enabling infinite-loop DoS via crafted packets"
                ),
                "rfc_reference": "RFC 1035",
                "remediation": (
                    "Track visited byte offsets during pointer following and "
                    "raise ValueError on revisit"
                ),
            },
            {
                "id": "no-txn-id-verification",
                "category": "vulnerability",
                "severity": "critical",
                "description": (
                    "send_query accepts any DNS response without verifying "
                    "that the transaction ID matches the query, enabling "
                    "cache poisoning via spoofed responses"
                ),
                "rfc_reference": "RFC 5452",
                "remediation": (
                    "Extract query transaction ID and loop on recvfrom until "
                    "a response with matching ID is received"
                ),
            },
            {
                "id": "no-cname-following",
                "category": "missing_feature",
                "severity": "high",
                "description": (
                    "Resolver ignores CNAME records in answers, failing "
                    "resolution for all CNAME-aliased domains"
                ),
                "rfc_reference": "RFC 1034",
                "remediation": (
                    "After checking for direct A answers, detect CNAME "
                    "records and recursively resolve the CNAME target"
                ),
            },
            {
                "id": "glueless-ns-failure",
                "category": "protocol_violation",
                "severity": "high",
                "description": (
                    "Resolver returns None when NS delegation lacks glue A "
                    "records instead of resolving the NS hostname"
                ),
                "rfc_reference": "RFC 1035",
                "remediation": (
                    "When no glue record exists, recursively resolve the NS "
                    "hostname to obtain its IP before continuing iteration"
                ),
            },
            {
                "id": "no-edns0-support",
                "category": "protocol_violation",
                "severity": "medium",
                "description": (
                    "Outgoing queries lack EDNS0 OPT pseudo-record, limiting "
                    "UDP responses to 512 bytes and causing truncation"
                ),
                "rfc_reference": "RFC 6891",
                "remediation": (
                    "Append OPT record (type 41) with UDP payload size 4096 "
                    "to the additional section of every query"
                ),
            },
            {
                "id": "insufficient-recv-buffer",
                "category": "protocol_violation",
                "severity": "high",
                "description": (
                    "Socket receive buffer is 512 bytes, which truncates "
                    "EDNS0-sized responses even after EDNS0 is enabled — "
                    "this interacts with the missing EDNS0 to silently "
                    "corrupt large DNS responses"
                ),
                "rfc_reference": "RFC 6891",
                "remediation": (
                    "Increase recvfrom buffer to 4096 bytes to match the "
                    "EDNS0 advertised payload size"
                ),
            },
        ],
        "risk_assessment": "critical",
        "test_methodology": (
            "Combined code review of resolver.py with live DNS testing "
            "using dig and tshark. Code review identified compression "
            "pointer loop vulnerability, missing CNAME/glueless handling, "
            "absent EDNS0 OPT record, undersized recv buffer, and "
            "missing transaction ID verification. Live testing with "
            "tshark packet capture confirmed missing EDNS0 in outgoing "
            "queries. dig +trace and +short queries established reference "
            "behavior for CNAME chains and delegation patterns."
        ),
    }

    with open(AUDIT_PATH, "w") as f:
        json.dump(audit, f, indent=2)

    print(f"Audit report written to {AUDIT_PATH}")


if __name__ == "__main__":
    main()
