#!/usr/bin/env python3
"""Generate ETW kernel memory dumps for forensic analysis task.

Creates two dumps:
  etw_dump.bin  — contains TWO SecurityTrace bypasses:
                  Session 12: LogBuffersLost union overlap
                  Session 14: Direct Kernel Object Modification (DKOM)
  etw_clean.bin — clean reference with no bypasses
"""

import struct
import uuid
import os
import hashlib

# Layout constants
SESSION_SIZE = 0x400
PROCESS_SIZE = 0x100
CONSUMER_SIZE = 0xA0
PROVIDER_SIZE = 0x20
HEADER_SIZE = 64

# Session field offsets (matching real WMI_LOGGER_CONTEXT)
OFF_LOGGER_ID = 0x000
OFF_BUFFER_SIZE = 0x004
OFF_MAX_EVENT_SIZE = 0x008
OFF_LOGGER_MODE = 0x00C
OFF_ACCEPT_NEW_EVENTS = 0x010
OFF_GET_CPU_CLOCK = 0x018
OFF_LOGGER_THREAD = 0x020
OFF_LOGGER_STATUS = 0x028
OFF_FAILURE_REASON = 0x02C
OFF_LOG_BUFFERS_LOST = 0x070
OFF_LOG_BUFFERS_WRITTEN = 0x074
OFF_LOG_BUFFERS_REALTIME = 0x078
OFF_LOGGER_NAME_LEN = 0x088
OFF_LOGGER_NAME_MAXLEN = 0x08A
OFF_LOGGER_NAME_BUF = 0x090
OFF_LOG_FILE_NAME_LEN = 0x098
OFF_FLAGS = 0x330
OFF_NUM_PROVIDERS = 0x340
OFF_PROVIDER_LIST = 0x348
OFF_NUM_CONSUMERS = 0x350
OFF_CONSUMER_LIST = 0x358

# Consumer field offsets (matching ETW_REALTIME_CONSUMER)
OFF_CONSUMER_FLINK = 0x000
OFF_CONSUMER_BLINK = 0x008
OFF_CONSUMER_PROC_HANDLE = 0x010
OFF_CONSUMER_PROC_OBJECT = 0x018
OFF_CONSUMER_LOGGER_ID = 0x058
OFF_CONSUMER_FLAGS = 0x05A

# Process field offsets (matching EPROCESS subset)
OFF_PROC_PID = 0x000
OFF_PROC_NAME = 0x008
OFF_PROC_PROTECTION = 0x020

# Flag bits (WMI_LOGGER_CONTEXT.Flags)
FLAG_PERSISTENT = 1 << 0
FLAG_AUTOLOGGER = 1 << 1
FLAG_FSREADY = 1 << 2
FLAG_REALTIME = 1 << 3
FLAG_WOW = 1 << 4
FLAG_KERNELTRACE = 1 << 5
FLAG_NOMOREENABLE = 1 << 6
FLAG_STACKTRACING = 1 << 7
FLAG_SECURITY_TRACE = 1 << 14
FLAG_LASTBRANCHTRACING = 1 << 15

# Protection levels (PS_PROTECTION)
PROT_NONE = 0x00
PROT_AM_PPL = 0x31
PROT_LSA_PPL = 0x41
PROT_WIN_PP = 0x52

# Known provider GUIDs
GUID_THREAT_INTEL = uuid.UUID("f4e1897c-bb5d-5668-f1d8-040f4d8dd344")
GUID_KERNEL_AUDIT_API = uuid.UUID("e02a841c-75a3-4fa7-afc8-ae09cf9b7f23")
GUID_SECURITY_AUDITING = uuid.UUID("54849625-5478-4994-a5ba-3e3b0328c30d")
GUID_SERVICES = uuid.UUID("0063715b-eeda-4007-9429-ad526f62696e")
GUID_DEFENDER_1 = uuid.UUID("11cd958a-c507-4ef3-b3f2-5fd9dfbd2c24")
GUID_DEFENDER_2 = uuid.UUID("e4b70372-261f-4c54-8fa8-a39dc3f4b81e")
GUID_DIAGTRACK = uuid.UUID("56dc463b-97e8-4b59-e836-ab7c9bb96301")
GUID_WINKERNEL = uuid.UUID("9e814aad-3204-11d2-9a82-006008a86939")


def encode_string_utf16le(s):
    return s.encode('utf-16-le')


def guid_to_bytes_le(g):
    """Convert UUID to Windows GUID binary format (mixed endian)."""
    return g.bytes_le


def fill_noise(buf, start, length, seed=0xA5):
    """Fill a region with deterministic noise to simulate uninitialized memory."""
    for i in range(length):
        h = hashlib.md5(struct.pack("<II", seed, start + i)).digest()
        buf[start + i] = h[0]


def generate_dump(sessions, processes, output_path):
    """Generate a single ETW memory dump file."""
    num_sessions = len(sessions)
    num_processes = len(processes)

    all_consumers = []
    all_providers = []
    for s in sessions:
        for proc_idx in s["consumers"]:
            all_consumers.append({"session": s, "proc_idx": proc_idx})
        for guid in s["providers"]:
            all_providers.append({"session": s, "guid": guid})

    num_consumers = len(all_consumers)
    num_providers = len(all_providers)

    # Calculate table offsets
    session_table_offset = HEADER_SIZE
    process_table_offset = session_table_offset + num_sessions * SESSION_SIZE
    consumer_table_offset = process_table_offset + num_processes * PROCESS_SIZE
    provider_table_offset = consumer_table_offset + num_consumers * CONSUMER_SIZE
    string_table_offset = provider_table_offset + num_providers * PROVIDER_SIZE

    # Build string table
    string_entries = {}
    cur_str_off = string_table_offset
    for s in sessions:
        encoded = encode_string_utf16le(s["name"])
        string_entries[s["name"]] = cur_str_off
        cur_str_off += len(encoded) + 2

    total_size = cur_str_off

    # Create dump buffer
    dump = bytearray(total_size)

    # Fill with deterministic noise
    for i in range(0, total_size, 4096):
        chunk = min(4096, total_size - i)
        fill_noise(dump, i, chunk, seed=0xDEAD + i)

    # === WRITE HEADER ===
    dump[0:8] = b"ETWDUMP1"
    struct.pack_into("<I", dump, 0x08, num_sessions)
    struct.pack_into("<I", dump, 0x0C, num_processes)
    struct.pack_into("<I", dump, 0x10, num_consumers)
    struct.pack_into("<I", dump, 0x14, 0)
    struct.pack_into("<Q", dump, 0x18, session_table_offset)
    struct.pack_into("<Q", dump, 0x20, process_table_offset)
    struct.pack_into("<Q", dump, 0x28, consumer_table_offset)
    struct.pack_into("<Q", dump, 0x30, string_table_offset)
    struct.pack_into("<Q", dump, 0x38, provider_table_offset)

    # === WRITE SESSIONS ===
    consumer_idx = 0
    provider_idx = 0
    for i, s in enumerate(sessions):
        base = session_table_offset + i * SESSION_SIZE

        struct.pack_into("<I", dump, base + OFF_LOGGER_ID, s["id"])
        struct.pack_into("<I", dump, base + OFF_BUFFER_SIZE, s["bufsz"])
        struct.pack_into("<I", dump, base + OFF_MAX_EVENT_SIZE, s["maxev"])
        struct.pack_into("<I", dump, base + OFF_LOGGER_MODE, s["mode"])
        struct.pack_into("<i", dump, base + OFF_ACCEPT_NEW_EVENTS, 1)

        struct.pack_into("<Q", dump, base + OFF_GET_CPU_CLOCK,
                         0xFFFFF80000100000 + i * 0x10)
        struct.pack_into("<Q", dump, base + OFF_LOGGER_THREAD,
                         0xFFFFD00000000000 + s["id"] * 0x1000)
        struct.pack_into("<i", dump, base + OFF_LOGGER_STATUS, s["status"])
        struct.pack_into("<I", dump, base + OFF_FAILURE_REASON, 0)

        # LogBuffersLost / LogBuffersWritten / RealTimeBuffersDelivered
        struct.pack_into("<I", dump, base + OFF_LOG_BUFFERS_LOST,
                         s.get("log_buffers_lost", 0))
        struct.pack_into("<I", dump, base + OFF_LOG_BUFFERS_WRITTEN,
                         s.get("log_buffers_written", 0))
        struct.pack_into("<I", dump, base + OFF_LOG_BUFFERS_REALTIME,
                         s.get("log_buffers_realtime", 0))

        # Logger name (UNICODE_STRING)
        name_encoded = encode_string_utf16le(s["name"])
        name_len = len(name_encoded)
        struct.pack_into("<H", dump, base + OFF_LOGGER_NAME_LEN, name_len)
        struct.pack_into("<H", dump, base + OFF_LOGGER_NAME_MAXLEN, name_len + 2)
        struct.pack_into("<I", dump, base + OFF_LOGGER_NAME_LEN + 4, 0)
        struct.pack_into("<Q", dump, base + OFF_LOGGER_NAME_BUF,
                         string_entries[s["name"]])

        # Flags (the critical field at offset 0x330)
        struct.pack_into("<I", dump, base + OFF_FLAGS, s["flags"])
        struct.pack_into("<I", dump, base + OFF_FLAGS + 4, 0)

        # Provider info
        num_sess_providers = len(s["providers"])
        struct.pack_into("<I", dump, base + OFF_NUM_PROVIDERS, num_sess_providers)
        struct.pack_into("<I", dump, base + OFF_NUM_PROVIDERS + 4, 0)
        if num_sess_providers > 0:
            struct.pack_into("<Q", dump, base + OFF_PROVIDER_LIST,
                             provider_table_offset + provider_idx * PROVIDER_SIZE)
        else:
            struct.pack_into("<Q", dump, base + OFF_PROVIDER_LIST, 0)

        # Consumer info
        num_sess_consumers = len(s["consumers"])
        struct.pack_into("<I", dump, base + OFF_NUM_CONSUMERS, num_sess_consumers)
        struct.pack_into("<I", dump, base + OFF_NUM_CONSUMERS + 4, 0)
        if num_sess_consumers > 0:
            struct.pack_into("<Q", dump, base + OFF_CONSUMER_LIST,
                             consumer_table_offset + consumer_idx * CONSUMER_SIZE)
        else:
            struct.pack_into("<Q", dump, base + OFF_CONSUMER_LIST, 0)

        provider_idx += num_sess_providers
        consumer_idx += num_sess_consumers

    # === WRITE PROCESSES ===
    for i, p in enumerate(processes):
        base = process_table_offset + i * PROCESS_SIZE

        struct.pack_into("<Q", dump, base + OFF_PROC_PID, p["pid"])

        name_bytes = p["name"].encode('ascii')[:15]
        for j in range(16):
            dump[base + OFF_PROC_NAME + j] = 0
        dump[base + OFF_PROC_NAME:base + OFF_PROC_NAME + len(name_bytes)] = name_bytes

        struct.pack_into("<B", dump, base + OFF_PROC_PROTECTION, p["protection"])

    # === WRITE CONSUMERS ===
    consumer_idx = 0
    for s in sessions:
        for proc_idx in s["consumers"]:
            base = consumer_table_offset + consumer_idx * CONSUMER_SIZE

            struct.pack_into("<Q", dump, base + OFF_CONSUMER_FLINK, 0)
            struct.pack_into("<Q", dump, base + OFF_CONSUMER_BLINK, 0)
            struct.pack_into("<Q", dump, base + OFF_CONSUMER_PROC_HANDLE,
                             0xFFFFFFFF80000000 + proc_idx * 4)
            struct.pack_into("<Q", dump, base + OFF_CONSUMER_PROC_OBJECT,
                             process_table_offset + proc_idx * PROCESS_SIZE)
            struct.pack_into("<H", dump, base + OFF_CONSUMER_LOGGER_ID, s["id"])
            struct.pack_into("<B", dump, base + OFF_CONSUMER_FLAGS, 0)

            consumer_idx += 1

    # === WRITE PROVIDERS ===
    provider_idx = 0
    for s in sessions:
        for guid in s["providers"]:
            base = provider_table_offset + provider_idx * PROVIDER_SIZE

            dump[base:base + 16] = guid_to_bytes_le(guid)
            struct.pack_into("<Q", dump, base + 0x10, 0xFFFFFFFFFFFFFFFF)
            struct.pack_into("<B", dump, base + 0x18, 0xFF)

            provider_idx += 1

    # === WRITE STRING TABLE ===
    for name, offset in string_entries.items():
        encoded = encode_string_utf16le(name)
        dump[offset:offset + len(encoded)] = encoded
        dump[offset + len(encoded):offset + len(encoded) + 2] = b'\x00\x00'

    # Write output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(dump)

    return total_size


def main():
    processes = [
        {"pid": 4, "name": "System", "protection": PROT_NONE},
        {"pid": 672, "name": "lsass.exe", "protection": PROT_LSA_PPL},
        {"pid": 2848, "name": "MsMpEng.exe", "protection": PROT_AM_PPL},
        {"pid": 5932, "name": "ThreatIntel.exe", "protection": PROT_NONE},
        {"pid": 1028, "name": "svchost.exe", "protection": PROT_NONE},
        {"pid": 6844, "name": "AuditCapture.exe", "protection": PROT_NONE},
    ]

    # Common sessions shared between attack and clean dumps (10 sessions)
    base_sessions = [
        {
            "id": 2, "name": "NT Kernel Logger",
            "flags": FLAG_KERNELTRACE | FLAG_REALTIME,
            "consumers": [], "providers": [GUID_WINKERNEL],
            "mode": 0x100, "status": 0, "bufsz": 64, "maxev": 65536,
            "log_buffers_lost": 0, "log_buffers_written": 42871,
            "log_buffers_realtime": 42871,
        },
        {
            "id": 3, "name": "EventLog-Security",
            "flags": FLAG_SECURITY_TRACE | FLAG_AUTOLOGGER | FLAG_FSREADY,
            "consumers": [1], "providers": [GUID_SECURITY_AUDITING],
            "mode": 0x100, "status": 0, "bufsz": 64, "maxev": 65536,
            "log_buffers_lost": 1, "log_buffers_written": 15832,
            "log_buffers_realtime": 0,
        },
        {
            "id": 4, "name": "DefenderApiLogger",
            "flags": FLAG_SECURITY_TRACE | FLAG_AUTOLOGGER | FLAG_REALTIME,
            "consumers": [2], "providers": [GUID_DEFENDER_1, GUID_SERVICES],
            "mode": 0x100, "status": 0, "bufsz": 128, "maxev": 65536,
            "log_buffers_lost": 0, "log_buffers_written": 8744,
            "log_buffers_realtime": 8744,
        },
        {
            "id": 5, "name": "DefenderAuditLogger",
            "flags": FLAG_SECURITY_TRACE | FLAG_AUTOLOGGER | FLAG_REALTIME,
            "consumers": [2], "providers": [GUID_DEFENDER_2],
            "mode": 0x100, "status": 0, "bufsz": 128, "maxev": 65536,
            "log_buffers_lost": 2, "log_buffers_written": 3211,
            "log_buffers_realtime": 3211,
        },
        {
            "id": 6, "name": "EventLog-Application",
            "flags": FLAG_AUTOLOGGER | FLAG_REALTIME,
            "consumers": [], "providers": [],
            "mode": 0x100, "status": 0, "bufsz": 64, "maxev": 65536,
            "log_buffers_lost": 0, "log_buffers_written": 1200,
            "log_buffers_realtime": 1200,
        },
        {
            "id": 7, "name": "EventLog-System",
            "flags": FLAG_AUTOLOGGER | FLAG_REALTIME,
            "consumers": [], "providers": [],
            "mode": 0x100, "status": 0, "bufsz": 64, "maxev": 65536,
            "log_buffers_lost": 0, "log_buffers_written": 980,
            "log_buffers_realtime": 980,
        },
        {
            "id": 8, "name": "DiagLog",
            "flags": FLAG_REALTIME,
            "consumers": [], "providers": [],
            "mode": 0x100, "status": 0, "bufsz": 32, "maxev": 65536,
            "log_buffers_lost": 0, "log_buffers_written": 120,
            "log_buffers_realtime": 120,
        },
        {
            "id": 9, "name": "AutoLogger-DiagTrack",
            "flags": FLAG_AUTOLOGGER,
            "consumers": [], "providers": [GUID_DIAGTRACK],
            "mode": 0x0, "status": 0, "bufsz": 64, "maxev": 65536,
            "log_buffers_lost": 5, "log_buffers_written": 6700,
            "log_buffers_realtime": 0,
        },
        {
            "id": 10, "name": "ReadyBoot",
            "flags": FLAG_AUTOLOGGER | FLAG_PERSISTENT,
            "consumers": [], "providers": [],
            "mode": 0x0, "status": 0, "bufsz": 128, "maxev": 65536,
            "log_buffers_lost": 0, "log_buffers_written": 450,
            "log_buffers_realtime": 0,
        },
        {
            "id": 11, "name": "WdiContextLog",
            "flags": FLAG_REALTIME,
            "consumers": [], "providers": [],
            "mode": 0x100, "status": 0, "bufsz": 32, "maxev": 32768,
            "log_buffers_lost": 0, "log_buffers_written": 88,
            "log_buffers_realtime": 88,
        },
    ]

    assert len(base_sessions) == 10, f"Expected 10 base sessions, got {len(base_sessions)}"

    # ATTACK session 12: SecurityTrace bypass via LogBuffersLost union overlap
    # LogBuffersLost = 0x4008 = Flags value, proving the union overlap technique
    attack_session_12 = {
        "id": 12, "name": "0-ThreatIntelConsumer",
        "flags": FLAG_SECURITY_TRACE | FLAG_REALTIME,  # 0x4008
        "consumers": [3],  # process index 3 = ThreatIntel.exe (PROT_NONE)
        "providers": [GUID_THREAT_INTEL],
        "mode": 0x100, "status": 0, "bufsz": 64, "maxev": 65536,
        "log_buffers_lost": FLAG_SECURITY_TRACE | FLAG_REALTIME,  # 0x4008 = union overlap evidence
        "log_buffers_written": 157,
        "log_buffers_realtime": 157,
    }

    # ATTACK session 14: SecurityTrace bypass via DKOM
    # LogBuffersLost = 7 (normal), but Flags has SecurityTrace set independently
    # An unprotected consumer consumes from the Kernel-Audit-API provider
    attack_session_14 = {
        "id": 14, "name": "SecurityAuditConsumer",
        "flags": FLAG_SECURITY_TRACE | FLAG_REALTIME,  # 0x4008
        "consumers": [5],  # process index 5 = AuditCapture.exe (PROT_NONE)
        "providers": [GUID_KERNEL_AUDIT_API],
        "mode": 0x100, "status": 0, "bufsz": 64, "maxev": 65536,
        "log_buffers_lost": 7,  # Normal value — NOT matching Flags = DKOM evidence
        "log_buffers_written": 312,
        "log_buffers_realtime": 312,
    }

    # CLEAN session 12: Benign diagnostic session
    clean_session_12 = {
        "id": 12, "name": "RundownLogger",
        "flags": FLAG_REALTIME,  # 0x8, no SecurityTrace
        "consumers": [2],  # process index 2 = MsMpEng.exe (AM-PPL)
        "providers": [GUID_DIAGTRACK],
        "mode": 0x100, "status": 0, "bufsz": 64, "maxev": 65536,
        "log_buffers_lost": 3,
        "log_buffers_written": 890,
        "log_buffers_realtime": 890,
    }

    # CLEAN session 14: Benign performance trace
    clean_session_14 = {
        "id": 14, "name": "PerfTraceLogger",
        "flags": FLAG_REALTIME,  # 0x8, no SecurityTrace
        "consumers": [],
        "providers": [],
        "mode": 0x100, "status": 0, "bufsz": 32, "maxev": 65536,
        "log_buffers_lost": 0,
        "log_buffers_written": 150,
        "log_buffers_realtime": 150,
    }

    tail_session = {
        "id": 13, "name": "Circular Kernel Context Logger",
        "flags": FLAG_REALTIME,
        "consumers": [], "providers": [],
        "mode": 0x108, "status": 0, "bufsz": 32, "maxev": 65536,
        "log_buffers_lost": 0, "log_buffers_written": 200,
        "log_buffers_realtime": 200,
    }

    attack_sessions = base_sessions + [attack_session_12, tail_session, attack_session_14]
    clean_sessions = base_sessions + [clean_session_12, tail_session, clean_session_14]

    assert len(attack_sessions) == 13, f"Expected 13 attack sessions, got {len(attack_sessions)}"
    assert len(clean_sessions) == 13, f"Expected 13 clean sessions, got {len(clean_sessions)}"
    assert len(processes) == 6, f"Expected 6 processes, got {len(processes)}"

    size1 = generate_dump(attack_sessions, processes, "/app/etw_dump.bin")
    size2 = generate_dump(clean_sessions, processes, "/app/etw_clean.bin")

    # Verify the output binaries have the correct session count
    with open("/app/etw_dump.bin", "rb") as f:
        header = f.read(64)
    written_sessions = struct.unpack_from("<I", header, 0x08)[0]
    written_processes = struct.unpack_from("<I", header, 0x0C)[0]
    assert written_sessions == 13, f"Attack dump has {written_sessions} sessions, expected 13"
    assert written_processes == 6, f"Attack dump has {written_processes} processes, expected 6"

    print(f"Generated attack dump: {size1} bytes -> /app/etw_dump.bin ({written_sessions} sessions, {written_processes} processes)")
    print(f"Generated clean dump: {size2} bytes -> /app/etw_clean.bin")


if __name__ == "__main__":
    main()
