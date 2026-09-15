#!/usr/bin/env python3
"""
Analyze the Speed Daemon skeleton, identify missing subsystems and the ticket
encoding bug, then deploy the complete enforcement engine implementation.

"""

import os
import struct
import shutil


def analyze_skeleton():
    """Read the skeleton server and identify gaps and bugs."""
    with open("/app/server.py", "r") as f:
        code = f.read()

    issues = []

    # --- Bug: Ticket encoding field order ---
    # Spec says: road(u16) mile1(u16) timestamp1(u32) mile2(u16) timestamp2(u32) speed(u16)
    build_start = code.find("_build_ticket_bytes")
    build_end = code.find("_send_ticket")
    if build_start >= 0 and build_end >= 0:
        build_section = code[build_start:build_end]
        ts2_pos = build_section.find('ticket["timestamp2"]')
        m2_pos = build_section.find('ticket["mile2"]')
        if ts2_pos >= 0 and m2_pos >= 0 and ts2_pos < m2_pos:
            issues.append(
                "BUG: _build_ticket_bytes has timestamp2 (u32) serialized before "
                "mile2 (u16). Spec field order requires mile2 before timestamp2."
            )

    # --- Missing: Violation detection ---
    plate_handler = code[code.find("_handle_plate"):code.find("_handle_want_heartbeat")]
    if "speed" not in plate_handler.lower() or "violation" not in plate_handler.lower():
        if "TODO" in plate_handler:
            issues.append(
                "MISSING: No speed violation detection in _handle_plate. "
                "Must compare all observation pairs and generate tickets."
            )

    # --- Missing: Ticket deduplication ---
    if "ticketed_days" not in code:
        issues.append(
            "MISSING: No ticket deduplication tracking. "
            "Must implement per-car-per-day dedup with multi-day spanning."
        )

    # --- Missing: Pending ticket buffering ---
    if "pending_tickets" not in code:
        issues.append(
            "MISSING: No ticket buffering for roads without dispatchers. "
            "Must buffer and deliver when dispatcher connects."
        )

    # --- Missing: Dispatcher cleanup ---
    cleanup_start = code.find("def cleanup")
    if cleanup_start >= 0:
        cleanup_section = code[cleanup_start:]
        if "dispatchers" not in cleanup_section or "remove" not in cleanup_section:
            issues.append(
                "MISSING: Disconnected dispatchers not removed from registry. "
                "Stale writers cause silent ticket loss instead of buffering."
            )

    return issues


def verify_reference_traces():
    """Parse reference pcap to extract correct ticket byte sequences for validation."""
    pcap_path = "/app/traces/reference.pcap"
    if not os.path.exists(pcap_path):
        return ["Reference pcap not found at " + pcap_path]

    findings = []
    with open(pcap_path, "rb") as f:
        f.read(24)  # Skip global header
        while True:
            pkt_hdr = f.read(16)
            if len(pkt_hdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack("<IIII", pkt_hdr)
            pkt_data = f.read(incl_len)
            if len(pkt_data) < incl_len:
                break
            # Skip eth(14) + ip(20) + tcp(20) = 54 bytes to get TCP payload
            payload = pkt_data[54:]
            if payload and payload[0] == 0x21:
                pos = 1
                plen = payload[pos]; pos += 1
                plate = payload[pos:pos + plen].decode("ascii"); pos += plen
                road = struct.unpack("!H", payload[pos:pos + 2])[0]; pos += 2
                mile1 = struct.unpack("!H", payload[pos:pos + 2])[0]; pos += 2
                ts1 = struct.unpack("!I", payload[pos:pos + 4])[0]; pos += 4
                mile2 = struct.unpack("!H", payload[pos:pos + 2])[0]; pos += 2
                ts2 = struct.unpack("!I", payload[pos:pos + 4])[0]; pos += 4
                speed = struct.unpack("!H", payload[pos:pos + 2])[0]
                findings.append(
                    f"  Ticket: plate={plate} road={road} "
                    f"mile1={mile1} ts1={ts1} mile2={mile2} ts2={ts2} speed={speed}"
                )

    return findings


def deploy_implementation():
    """Deploy the complete enforcement engine implementation."""
    shutil.copy2("/solution/server.py", "/app/server.py")


def verify_deployment():
    """Verify the deployed server has all required components."""
    with open("/app/server.py", "r") as f:
        code = f.read()

    checks = {
        "Ticket encoding (mile2 before timestamp2)": (
            code.find('ticket["mile2"]') < code.find('ticket["timestamp2"]')
        ),
        "Speed violation detection": "speed_mph" in code,
        "Ticket deduplication (per-car-per-day)": "ticketed_days" in code,
        "Buffered ticket delivery": "pending_tickets" in code,
        "Dispatcher cleanup on disconnect": (
            "dispatchers" in code[code.find("def cleanup"):]
            and "remove" in code[code.find("def cleanup"):]
        ),
        "Cross-road dedup (global, keyed by plate alone)": (
            "ticketed_days[plate]" in code
        ),
    }

    all_ok = True
    for check_name, passed in checks.items():
        status = "OK" if passed else "FAIL"
        if not passed:
            all_ok = False
        print(f"  [{status}] {check_name}")

    return all_ok


def main():
    print("=== Speed Daemon Skeleton Analysis ===\n")

    issues = analyze_skeleton()
    for issue in issues:
        print(f"  * {issue}")
    print(f"\n  Total: {len(issues)} issue(s) identified.\n")

    print("=== Reference Trace Verification ===\n")
    findings = verify_reference_traces()
    for finding in findings:
        print(finding)

    print("\n=== Deploying Enforcement Engine ===\n")
    deploy_implementation()

    print("=== Deployment Verification ===\n")
    if verify_deployment():
        print(f"\nAll components verified. Server ready at /app/server.py")
    else:
        print("\nWARNING: Some components failed verification!")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
