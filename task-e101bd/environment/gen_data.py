#!/usr/bin/env python3
"""Generate the binary station capture file and SQLite registry database.

Binary format (proprietary "MS0V" ground station log):

Header (24 bytes):
  Bytes 0-3:    Magic: "MS0V"
  Bytes 4-5:    Format version (uint16 LE)
  Bytes 6-7:    Total record count (uint16 LE)
  Bytes 8-15:   Station identifier (8 bytes, null-padded ASCII)
  Bytes 16-23:  Base timestamp (uint64 LE, microseconds since 2020-01-01)

Each record:
  Bytes 0-1:    Sync word: 0x1A 0x33
  Byte  2:      Record type (0x01=status, 0x02=message, 0x03=heartbeat)
  Bytes 3-6:    Timestamp delta from base (uint32 LE, microseconds)

  Type 0x02 (message) continues with:
    Byte  7:    RSSI (int8, dBm)
    Byte  8:    Message byte count (7 or 14)
    Bytes 9-N:  Raw transponder message bytes
    Byte  N+1:  XOR checksum of bytes 2..N

  Type 0x01 (status) continues with:
    Byte  7:    Status code (uint8: 0=nominal)
    Bytes 8-11: Cumulative message count (uint32 LE)
    Byte  12:   XOR checksum of bytes 2..11

  Type 0x03 (heartbeat) continues with:
    Byte  7:    XOR checksum of bytes 2..6
"""

import struct
import sqlite3
import os

# ── Raw Mode S hex messages (same content as original captures.txt) ──────────
# These are the actual transponder payloads in hex. The binary log wraps them
# with timestamps, RSSI, and a container checksum.

RECORDS = [
    # (type, ts_delta_us, payload_spec)
    # type: 's'=status, 'h'=heartbeat, 'm'=message

    ("s", 0,       (0, 0)),  # initial status: code=0, count=0

    # Aircraft A1B2C3: identification
    ("m", 100000,  (-42, "8DA1B2C320541331CB3D20C282F2")),
    # Aircraft D4E5F6: identification
    ("m", 250000,  (-35, "8DD4E5F6200815F7E39820FA5264")),
    # Noise: all-zero 14-byte message (DF=0, not DF17)
    ("m", 400000,  (-60, "00000000000000000000000000000000"[:28])),

    ("h", 500000,  None),

    # Aircraft 789ABC: identification
    ("m", 620000,  (-40, "8D789ABC2010C234CA0820F43511")),

    # Position messages (even frames)
    ("m", 810000,  (-38, "8DA1B2C358BA0318118E355AA502")),
    ("m", 920000,  (-33, "8DD4E5F65898825037E81CB550CF")),
    ("m", 1050000, (-37, "8D789ABC58D9003C6A8DBBBCA1CD")),

    # Corrupted CRC message (DEADBE)
    ("m", 1150000, (-50, "8DDEADBEEFEFEFEBEFEFEF37F594")),
    # Noise: all-FF 14-byte message
    ("m", 1280000, (-55, "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"[:28])),

    ("h", 1500000, None),

    # Position messages (odd frames)
    ("m", 1610000, (-39, "8DA1B2C358BA06A477F7235B89A9")),
    ("m", 1720000, (-34, "8DD4E5F6589885BDD1E8C11409DF")),
    ("m", 1830000, (-38, "8D789ABC58D907B2E07CF8DA6D51")),

    # Non-DF17 short message (DF=11, 7 bytes)
    ("m", 1950000, (-44, "5DA1B2C3000000")),

    # Velocity messages
    ("m", 2010000, (-45, "8DA1B2C39901C3002824007E8714")),
    ("m", 2130000, (-36, "8DD4E5F699057D80200400B43F6C")),
    ("m", 2250000, (-41, "8D789ABC99015B2B60540076FC85")),

    ("h", 2500000, None),

    ("s", 3000000, (0, 16)),  # final status: code=0, count=16
]


def xor_checksum(data: bytes) -> int:
    r = 0
    for b in data:
        r ^= b
    return r


def build_binary_log(path: str):
    num_records = len(RECORDS)
    base_ts = 1_609_459_200_000_000  # 2021-01-01 00:00:00 UTC in microseconds

    with open(path, "wb") as f:
        # ── Header (24 bytes) ─────────────────────────────────────────────
        header = struct.pack(
            "<4sHH8sQ",
            b"MS0V",           # magic
            2,                 # version
            num_records,       # record count
            b"KORD-R7\x00",   # station ID (8 bytes)
            base_ts,           # base timestamp
        )
        assert len(header) == 24
        f.write(header)

        # ── Records ───────────────────────────────────────────────────────
        msg_count = 0
        for rtype, ts_delta, payload_spec in RECORDS:
            # Sync word
            f.write(b"\x1a\x33")

            if rtype == "m":
                # Message record
                rssi, hex_msg = payload_spec
                msg_bytes = bytes.fromhex(hex_msg)
                msg_len = len(msg_bytes)

                # Checksum covers: type(1) + ts_delta(4) + rssi(1) + len(1) + msg(N)
                body = struct.pack("<BIbB", 0x02, ts_delta, rssi, msg_len) + msg_bytes
                chk = xor_checksum(body)
                f.write(body)
                f.write(struct.pack("B", chk))
                msg_count += 1

            elif rtype == "s":
                # Status record
                status_code, count = payload_spec
                body = struct.pack("<BIBI", 0x01, ts_delta, status_code, count)
                chk = xor_checksum(body)
                f.write(body)
                f.write(struct.pack("B", chk))

            elif rtype == "h":
                # Heartbeat record
                body = struct.pack("<BI", 0x03, ts_delta)
                chk = xor_checksum(body)
                f.write(body)
                f.write(struct.pack("B", chk))


def build_registry_db(path: str):
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE aircraft_registry (
            icao_hex   TEXT PRIMARY KEY,
            registration TEXT,
            type_code  TEXT,
            operator   TEXT,
            country    TEXT
        )
    """)
    entries = [
        ("A1B2C3", "N14001",  "B738", "United Airlines",   "United States"),
        ("D4E5F6", "G-EUPT",  "A320", "British Airways",   "United Kingdom"),
        ("789ABC", "D-AIMA",  "A388", "Lufthansa",         "Germany"),
        ("DEADBE", "VH-OQA",  "A388", "Qantas",            "Australia"),
        ("4CA123", "EI-DVI",  "B738", "Ryanair",           "Ireland"),
        ("3C4A5E", "D-ABYA",  "B748", "Lufthansa",         "Germany"),
        ("AC20D3", "C-FIVW",  "B77W", "Air Canada",        "Canada"),
        ("010024", "SU-GDL",  "B77W", "EgyptAir",          "Egypt"),
        ("71C3A1", "JA8089",  "B744", "ANA",               "Japan"),
        ("E48420", "PT-MUA",  "B77W", "LATAM Brasil",      "Brazil"),
    ]
    c.executemany(
        "INSERT INTO aircraft_registry VALUES (?, ?, ?, ?, ?)", entries
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    build_binary_log("/app/station_capture.bin")
    build_registry_db("/app/registry.db")
    print("Generated station_capture.bin and registry.db")
