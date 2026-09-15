#!/usr/bin/env python3
"""Analyze SOCKS5 session transcripts for RFC 1928/1929 conformance violations.

"""

import json
import os
import re


def parse_transcript(path):
    """Parse a hex transcript into (direction, bytes_or_None, raw_line) tuples."""
    messages = []
    comments = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#"):
                comments.append(line)
                continue
            if not (line.startswith("C>") or line.startswith("S>")):
                continue
            direction = line[0]  # 'C' or 'S'
            payload = line[3:].strip()
            if payload.startswith("["):
                messages.append((direction, None, payload))
                continue
            try:
                data = bytes.fromhex(payload.replace(" ", ""))
            except ValueError:
                continue
            messages.append((direction, data, payload))
    return messages, comments


def analyze_session(filepath):
    """Identify RFC violations in a single session transcript."""
    violations = []
    messages, comments = parse_transcript(filepath)
    fname = os.path.basename(filepath)

    # Find the CONNECT request and reply (skip method negotiation and auth)
    request_data = None
    reply_data = None

    for i, (d, data, raw) in enumerate(messages):
        if data is None:
            # Connection reset — check if preceded by an IPv6 CONNECT
            if i > 0:
                pd, pdata, _ = messages[i - 1]
                if pd == "C" and pdata and len(pdata) >= 4 and pdata[3] == 0x04:
                    violations.append({
                        "rfc": "1928",
                        "section": "5",
                        "description": (
                            "Server crashed on ATYP=0x04 (IPv6). "
                            "IPv6 addresses are 16 octets per RFC 1928 Section 5; "
                            "server likely reads only 4 bytes, causing a protocol "
                            "desynchronization and connection reset."
                        ),
                        "session": fname,
                    })
            continue

        if d != "S" or data is None:
            continue

        # Server replies with 10+ bytes are SOCKS5 command replies
        if len(data) >= 10 and data[0] == 0x05:
            reply_data = data
            # Find the preceding client request
            for j in range(i - 1, -1, -1):
                if messages[j][0] == "C" and messages[j][1] and len(messages[j][1]) >= 4:
                    cd = messages[j][1]
                    if cd[0] == 0x05 and cd[1] in (0x01, 0x02, 0x03):
                        request_data = cd
                        break

            ver, rep, rsv, atyp = data[0], data[1], data[2], data[3]

            # Check RSV byte
            if rsv != 0x00:
                violations.append({
                    "rfc": "1928",
                    "section": "6",
                    "description": (
                        f"Reply RSV (reserved) byte is 0x{rsv:02x} but must be "
                        f"0x00. RFC 1928 Section 6: 'Fields marked RESERVED (RSV) "
                        f"must be set to X\\'00\\''."
                    ),
                    "session": fname,
                })

            # Check reply code for unsupported commands
            if request_data:
                cmd = request_data[1]
                if cmd in (0x02, 0x03) and rep != 0x07:
                    cmd_name = "BIND" if cmd == 0x02 else "UDP ASSOCIATE"
                    violations.append({
                        "rfc": "1928",
                        "section": "6",
                        "description": (
                            f"Unsupported command {cmd_name} (CMD=0x{cmd:02x}) "
                            f"returned REP=0x{rep:02x} instead of REP=0x07 "
                            f"(command not supported). RFC 1928 Section 6 defines "
                            f"X'07' for commands the server does not support."
                        ),
                        "session": fname,
                    })

                # Check BND.PORT for successful CONNECT
                if cmd == 0x01 and rep == 0x00 and atyp == 0x01:
                    bnd_port = (data[8] << 8) | data[9]
                    # Extract target port from request
                    if request_data[3] == 0x01 and len(request_data) >= 10:
                        target_port = (request_data[8] << 8) | request_data[9]
                        if bnd_port == target_port:
                            violations.append({
                                "rfc": "1928",
                                "section": "6",
                                "description": (
                                    f"BND.PORT in CONNECT reply ({bnd_port}) "
                                    f"matches the target port. Per RFC 1928, "
                                    f"BND.ADDR and BND.PORT must reflect the "
                                    f"proxy's outbound local address and ephemeral "
                                    f"port, not the target's."
                                ),
                                "session": fname,
                            })

        # Auth sub-negotiation: 2-byte reply with VER=0x01
        if len(data) == 2 and data[0] == 0x01 and data[1] != 0x00:
            # Auth failure — check if credentials should have been valid
            cred_context = any(
                "users.conf" in c or "credential" in c.lower()
                for c in comments
            )
            if cred_context and i > 0:
                pd, pdata, _ = messages[i - 1]
                if pd == "C" and pdata and len(pdata) >= 2 and pdata[0] == 0x01:
                    violations.append({
                        "rfc": "1929",
                        "section": "2",
                        "description": (
                            "Auth sub-negotiation with VER=0x01 and valid "
                            "credentials was rejected. RFC 1929 Section 2 "
                            "specifies the sub-negotiation version as X'01'. "
                            "The server likely checks for VER=0x05 instead of "
                            "the correct VER=0x01."
                        ),
                        "session": fname,
                    })

    # Check for ACL bypass on domain connections
    dns_comments = [c for c in comments if "dns" in c.lower() or "resolution" in c.lower()]
    for info in dns_comments:
        ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", info)
        if not ip_match:
            continue
        resolved_ip = ip_match.group(1)
        if not resolved_ip.startswith("10."):
            continue
        # Check if server denied or allowed
        for d, data, raw in messages:
            if d == "S" and data and len(data) >= 10 and data[0] == 0x05:
                if data[1] != 0x02:  # Not denied
                    violations.append({
                        "rfc": "1928",
                        "section": "6",
                        "description": (
                            f"Domain-name CONNECT resolved to {resolved_ip} "
                            f"(denied by ACL rule 'deny 10.0.0.0/8') but server "
                            f"returned REP=0x{data[1]:02x} instead of REP=0x02 "
                            f"(not allowed by ruleset). ACL enforcement must "
                            f"apply to all connection types including domain-name "
                            f"addresses after DNS resolution."
                        ),
                        "session": fname,
                    })

    return violations


def main():
    transcript_dir = "/app/transcripts"
    all_violations = []

    for fname in sorted(os.listdir(transcript_dir)):
        if not fname.endswith(".txt"):
            continue
        path = os.path.join(transcript_dir, fname)
        violations = analyze_session(path)
        all_violations.extend(violations)

    with open("/app/conformance_report.json", "w") as f:
        json.dump(all_violations, f, indent=2)

    print(f"Conformance report: {len(all_violations)} violations found")
    for v in all_violations:
        print(f"  [{v['session']}] RFC {v['rfc']} §{v['section']}: "
              f"{v['description'][:80]}...")


if __name__ == "__main__":
    main()
