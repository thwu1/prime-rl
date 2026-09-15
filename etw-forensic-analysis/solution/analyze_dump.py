#!/usr/bin/env python3

"""
Solution: Parse ETW kernel memory dump, perform comparative technique evaluation
for each anomalous session, and create YARA detection rule.

Key steps:
1. Parse header for table offsets
2. Discover Flags field offset by scanning for known flag patterns
3. Identify all anomalous SecurityTrace sessions (unprotected consumers)
4. For each anomalous session, evaluate all 4 documented techniques against
   forensic evidence, identify the matching one, and rule out the other 3
5. Generate and write YARA detection rule
"""

import struct
import json
import uuid


def read_u8(data, off):
    return struct.unpack_from("<B", data, off)[0]


def read_u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def read_u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def read_u64(data, off):
    return struct.unpack_from("<Q", data, off)[0]


def read_string_utf16le(data, off, length):
    raw = data[off:off + length]
    return raw.decode("utf-16-le", errors="replace")


def guid_from_bytes_le(raw):
    """Convert 16 bytes in Windows mixed-endian GUID format to UUID string."""
    return str(uuid.UUID(bytes_le=bytes(raw)))


def discover_flags_offset(data, session_table_offset, num_sessions, session_size):
    """
    Discover the offset of the Flags field within session entries.

    "NT Kernel Logger" (first session, id=2) should have:
      KernelTrace(bit5) | RealTime(bit3) = 0x28

    Scan every 4-byte aligned offset after known fields, then validate
    against DefenderApiLogger (index 2) which should have 0x400A.
    """
    candidates = []
    for off in range(0x0A0, session_size, 4):
        val = read_u32(data, session_table_offset + off)
        if val == 0x28:
            candidates.append(off)

    # Validate against DefenderApiLogger (session index 2):
    # SecurityTrace|AutoLogger|RealTime = 0x400A
    defender_base = session_table_offset + 2 * session_size
    for off in candidates:
        val = read_u32(data, defender_base + off)
        if val == 0x400A:
            return off

    return 0x330  # fallback


def evaluate_technique(data, session_base, flags_val):
    """Evaluate which bypass technique was used based on forensic evidence.

    Compares LogBuffersLost (documented at 0x070) against Flags to
    determine the attack vector, and generates comparative ruling-out
    analysis for all four documented techniques.
    """
    log_buffers_lost = read_u32(data, session_base + 0x070)

    # Determine matching technique
    if log_buffers_lost == flags_val and log_buffers_lost >= 0x4000:
        # Union overlap: LogBuffersLost equals Flags exactly
        identified = "log_buffers_lost_union_overlap"
        ruling_out = {
            "direct_kernel_object_modification": (
                f"LogBuffersLost value (0x{log_buffers_lost:04X}) is abnormally high "
                f"and matches Flags (0x{flags_val:04X}) exactly — in DKOM, LogBuffersLost "
                f"remains at normal levels (0-100) since only the Flags field is patched"
            ),
            "provider_callback_hijacking": (
                f"SecurityTrace flag IS set on this session (Flags=0x{flags_val:04X}, "
                f"bit 14 active) — callback hijacking operates without setting "
                f"SecurityTrace and instead redirects provider notification callbacks"
            ),
            "handle_table_manipulation": (
                f"Consumer process has protection level 0x00 (no PPL/PP), indicating "
                f"no protection at all — handle table manipulation would present a "
                f"non-zero spoofed protection level inherited from a legitimate PPL process"
            ),
        }
        severity = "critical"
    elif log_buffers_lost < 100:
        # DKOM: LogBuffersLost normal, Flags independently modified
        identified = "direct_kernel_object_modification"
        ruling_out = {
            "log_buffers_lost_union_overlap": (
                f"LogBuffersLost value ({log_buffers_lost}) is in the normal range "
                f"(0-100) and does not match Flags value (0x{flags_val:04X}) — union "
                f"overlap requires LogBuffersLost to equal Flags exactly with a value >= 0x4000"
            ),
            "provider_callback_hijacking": (
                f"SecurityTrace flag IS set on this session (Flags=0x{flags_val:04X}, "
                f"bit 14 active) — callback hijacking does not set SecurityTrace and "
                f"instead replaces provider notification callback pointers"
            ),
            "handle_table_manipulation": (
                f"Consumer process has protection level 0x00 (no PPL/PP) — handle table "
                f"manipulation would show a non-zero protection level spoofed from a "
                f"legitimate PPL process's handle table, not zero protection"
            ),
        }
        severity = "critical"
    else:
        identified = "unknown"
        ruling_out = {}
        severity = "high"

    return identified, ruling_out, severity


def generate_yara_rule(ti_guid_bytes, audit_guid_bytes):
    """Generate a YARA rule to detect both SecurityTrace bypass patterns.

    The rule detects:
    1. ETWDUMP1 file magic at offset 0
    2. The 0x4008 (SecurityTrace|RealTime) LE pattern appearing >= 2 times
       (union overlap evidence: once at LogBuffersLost, once at Flags)
    3. Protected provider GUIDs that should not appear in sessions
       with unprotected consumers
    """
    ti_hex = " ".join(f"{b:02x}" for b in ti_guid_bytes)
    audit_hex = " ".join(f"{b:02x}" for b in audit_guid_bytes)

    rule = (
        'rule ETW_SecurityTrace_Bypass\n'
        '{\n'
        '    meta:\n'
        '        description = "Detects ETW SecurityTrace bypass via '
        'LogBuffersLost union overlap or DKOM targeting protected providers"\n'
        '        author = "Forensic Analyst"\n'
        '        severity = "critical"\n'
        '\n'
        '    strings:\n'
        '        $magic = "ETWDUMP1" ascii\n'
        '        $sec_realtime_le = { 08 40 00 00 }\n'
        f'        $ti_guid = {{ {ti_hex} }}\n'
        f'        $audit_guid = {{ {audit_hex} }}\n'
        '\n'
        '    condition:\n'
        '        $magic at 0\n'
        '        and #sec_realtime_le >= 2\n'
        '        and ($ti_guid or $audit_guid)\n'
        '}\n'
    )
    return rule


def main():
    with open("/app/etw_dump.bin", "rb") as f:
        data = f.read()

    # Verify magic
    magic = data[0:8]
    assert magic == b"ETWDUMP1", f"Bad magic: {magic}"

    # Parse header
    num_sessions = read_u32(data, 0x08)
    num_processes = read_u32(data, 0x0C)
    num_consumers = read_u32(data, 0x10)
    session_off = read_u64(data, 0x18)
    process_off = read_u64(data, 0x20)
    consumer_off = read_u64(data, 0x28)
    string_off = read_u64(data, 0x30)
    provider_off = read_u64(data, 0x38)

    print(f"Header: {num_sessions} sessions, {num_processes} processes, {num_consumers} consumers")

    SESSION_SIZE = 0x400
    PROCESS_SIZE = 0x100
    CONSUMER_SIZE = 0xA0
    PROVIDER_SIZE = 0x20

    # Discover undocumented Flags offset
    flags_offset = discover_flags_offset(data, session_off, num_sessions, SESSION_SIZE)
    print(f"Discovered Flags offset: 0x{flags_offset:03X}")

    # Consumer/provider fields are near Flags at known relative offsets
    off_num_providers = flags_offset + 0x10
    off_provider_list = flags_offset + 0x18
    off_num_consumers = flags_offset + 0x20
    off_consumer_list = flags_offset + 0x28

    SECURITY_TRACE_BIT = 14
    SECURITY_TRACE_MASK = 1 << SECURITY_TRACE_BIT  # 0x4000

    anomalous_sessions = []
    technique_analysis = []
    ti_guid_bytes = None
    audit_guid_bytes = None

    for i in range(num_sessions):
        base = session_off + i * SESSION_SIZE

        logger_id = read_u32(data, base + 0x000)
        name_len = read_u16(data, base + 0x088)
        name_buf_off = read_u64(data, base + 0x090)
        logger_name = read_string_utf16le(data, name_buf_off, name_len)

        flags = read_u32(data, base + flags_offset)

        # Only interested in SecurityTrace sessions
        if not (flags & SECURITY_TRACE_MASK):
            continue

        # Read consumers
        n_consumers = read_u32(data, base + off_num_consumers)
        if n_consumers == 0:
            continue

        consumer_list_off = read_u64(data, base + off_consumer_list)
        consumers = []

        for j in range(n_consumers):
            c_base = consumer_list_off + j * CONSUMER_SIZE
            proc_obj_off = read_u64(data, c_base + 0x018)

            pid = read_u64(data, proc_obj_off + 0x000)
            proc_name_raw = data[proc_obj_off + 0x008:proc_obj_off + 0x008 + 16]
            proc_name = proc_name_raw.split(b'\x00')[0].decode('ascii', errors='replace')
            protection = read_u8(data, proc_obj_off + 0x020)

            consumers.append({
                "pid": pid,
                "process_name": proc_name,
                "protection": protection,
            })

        # Only flag sessions where a consumer has NO protection (Type=0, Signer=0)
        has_unprotected = any(c["protection"] == 0x00 for c in consumers)
        if not has_unprotected:
            continue

        # Read providers
        n_providers = read_u32(data, base + off_num_providers)
        provider_list_off = read_u64(data, base + off_provider_list)
        providers = []
        for j in range(n_providers):
            p_base = provider_list_off + j * PROVIDER_SIZE
            guid_bytes = data[p_base:p_base + 16]
            guid_str = guid_from_bytes_le(guid_bytes)
            providers.append(guid_str)
            if "f4e1897c" in guid_str:
                ti_guid_bytes = guid_bytes
            if "e02a841c" in guid_str:
                audit_guid_bytes = guid_bytes

        # Evaluate bypass technique with comparative analysis
        identified, ruling_out, severity = evaluate_technique(data, base, flags)

        technique_analysis.append({
            "logger_id": logger_id,
            "identified_technique": identified,
            "ruling_out": ruling_out,
            "severity": severity,
        })

        anomalous_sessions.append({
            "logger_id": logger_id,
            "logger_name": logger_name,
            "flags_hex": f"0x{flags:04X}",
            "consumers": [
                {
                    "pid": c["pid"],
                    "process_name": c["process_name"],
                    "protection_level_hex": f"0x{c['protection']:02X}",
                }
                for c in consumers
            ],
            "providers": providers,
        })

    # Build findings
    findings = {
        "anomalous_sessions": anomalous_sessions,
        "security_trace_bit_position": SECURITY_TRACE_BIT,
        "security_trace_mask_hex": f"0x{SECURITY_TRACE_MASK:04X}",
        "technique_analysis": technique_analysis,
    }

    with open("/app/findings.json", "w") as f:
        json.dump(findings, f, indent=2)
    print("Wrote /app/findings.json")

    print(f"Found {len(anomalous_sessions)} anomalous sessions")

    # Generate YARA detection rule
    if ti_guid_bytes and audit_guid_bytes:
        yara_rule = generate_yara_rule(ti_guid_bytes, audit_guid_bytes)
    elif ti_guid_bytes:
        ti_hex = " ".join(f"{b:02x}" for b in ti_guid_bytes)
        yara_rule = (
            'rule ETW_SecurityTrace_Bypass\n'
            '{\n'
            '    meta:\n'
            '        description = "Detects ETW SecurityTrace bypass"\n'
            '    strings:\n'
            '        $magic = "ETWDUMP1" ascii\n'
            '        $sec_realtime_le = { 08 40 00 00 }\n'
            f'        $ti_guid = {{ {ti_hex} }}\n'
            '    condition:\n'
            '        $magic at 0 and #sec_realtime_le >= 2 and $ti_guid\n'
            '}\n'
        )
    else:
        print("WARNING: Provider GUIDs not found — cannot generate YARA rule")
        return

    with open("/app/detect_bypass.yar", "w") as f:
        f.write(yara_rule)
    print("Wrote /app/detect_bypass.yar")

    print(json.dumps(findings, indent=2))


if __name__ == "__main__":
    main()
