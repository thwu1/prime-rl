#!/usr/bin/env python3

"""
Solution decoder: parses the proprietary binary ground station log,
decodes Mode S / ADS-B messages, and cross-references with the SQLite
aircraft registry.
"""

import json
import math
import struct
import sqlite3
import sys


# ═══════════════════════════════════════════════════════════════════════
# Binary container parser
# ═══════════════════════════════════════════════════════════════════════

def parse_binary_log(filepath):
    """Parse the MS0V binary log and yield raw Mode S message byte arrays."""
    with open(filepath, "rb") as f:
        data = f.read()

    # ── Header (24 bytes) ────────────────────────────────────────────
    magic = data[0:4]
    assert magic == b"MS0V", f"Bad magic: {magic}"
    version, num_records = struct.unpack_from("<HH", data, 4)
    station_id = data[8:16].rstrip(b"\x00").decode("ascii")
    base_ts = struct.unpack_from("<Q", data, 16)[0]

    pos = 24  # current read position

    messages = []

    for _ in range(num_records):
        # Sync word
        sync = data[pos:pos+2]
        assert sync == b"\x1a\x33", f"Bad sync at offset {pos}: {sync.hex()}"
        pos += 2

        # Record type + timestamp delta (common to all record types)
        rec_type = data[pos]
        ts_delta = struct.unpack_from("<I", data, pos + 1)[0]

        if rec_type == 0x02:
            # Message record
            rssi = struct.unpack_from("<b", data, pos + 5)[0]
            msg_len = data[pos + 6]
            msg_bytes = data[pos + 7: pos + 7 + msg_len]
            chk_expected = data[pos + 7 + msg_len]

            # Verify XOR checksum
            body = data[pos: pos + 7 + msg_len]
            chk = 0
            for b in body:
                chk ^= b
            if chk == chk_expected:
                messages.append(msg_bytes)

            pos += 7 + msg_len + 1  # type(1)+ts(4)+rssi(1)+len(1)+msg(N)+chk(1)

        elif rec_type == 0x01:
            # Status record: type(1) + ts(4) + status(1) + count(4) + chk(1) = 11
            pos += 11

        elif rec_type == 0x03:
            # Heartbeat record: type(1) + ts(4) + chk(1) = 6
            pos += 6

        else:
            # Unknown record type — skip by scanning for next sync
            pos += 5
            while pos < len(data) - 1:
                if data[pos] == 0x1a and data[pos+1] == 0x33:
                    break
                pos += 1

    return messages


# ═══════════════════════════════════════════════════════════════════════
# CRC-24 (Mode S)
# ═══════════════════════════════════════════════════════════════════════

def crc24_residual(msg_bytes):
    """Compute CRC-24 residual. Returns 0 for valid messages."""
    GENERATOR = 0xFFF409
    n_bits = len(msg_bytes) * 8
    msg_int = int.from_bytes(msg_bytes, "big")
    for i in range(n_bits - 24):
        if msg_int & (1 << (n_bits - 1 - i)):
            msg_int ^= GENERATOR << (n_bits - 25 - i)
    return msg_int & 0xFFFFFF


# ═══════════════════════════════════════════════════════════════════════
# Callsign decoding (TC 1-4)
# ═══════════════════════════════════════════════════════════════════════

_CHARSET = ["_"] * 64
_CHARSET[32] = " "
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _CHARSET[_i + 1] = _c
for _i, _c in enumerate("0123456789"):
    _CHARSET[_i + 48] = _c


def decode_callsign(me_int):
    chars = []
    for i in range(8):
        val = (me_int >> (42 - i * 6)) & 0x3F
        if 0 <= val < len(_CHARSET) and _CHARSET[val] != "_":
            chars.append(_CHARSET[val])
        else:
            chars.append(" ")
    return "".join(chars).strip()


# ═══════════════════════════════════════════════════════════════════════
# Altitude decoding
# ═══════════════════════════════════════════════════════════════════════

def decode_altitude(alt_code):
    q_bit = (alt_code >> 7) & 1
    if q_bit == 1:
        n = ((alt_code >> 8) & 0xF) << 7 | (alt_code & 0x7F)
        return n * 25 - 1000
    return None


# ═══════════════════════════════════════════════════════════════════════
# CPR position decoding
# ═══════════════════════════════════════════════════════════════════════

def _nl(lat):
    if abs(lat) >= 87.0:
        return 1
    NZ = 15
    cos_lat = math.cos(math.pi * abs(lat) / 180.0)
    val = 1.0 - (1.0 - math.cos(math.pi / (2.0 * NZ))) / (cos_lat * cos_lat)
    val = max(-1.0, min(1.0, val))
    return int(math.floor(2.0 * math.pi / math.acos(val)))


def decode_cpr_global(yz_even, xz_even, yz_odd, xz_odd, use_odd=True):
    P17 = 2 ** 17
    dlat0 = 360.0 / 60.0
    dlat1 = 360.0 / 59.0
    f_even = yz_even / P17
    f_odd = yz_odd / P17

    j = int(math.floor(59.0 * f_even - 60.0 * f_odd + 0.5))

    rlat0 = dlat0 * ((j % 60) + f_even)
    rlat1 = dlat1 * ((j % 59) + f_odd)

    if rlat0 >= 270.0:
        rlat0 -= 360.0
    if rlat1 >= 270.0:
        rlat1 -= 360.0

    nl0 = _nl(rlat0)
    nl1 = _nl(rlat1)
    if nl0 != nl1:
        return None, None

    fe_lon = xz_even / P17
    fo_lon = xz_odd / P17

    if use_odd:
        rlat = rlat1
        nl_val = nl1
        ni = max(nl_val - 1, 1)
        dlon = 360.0 / ni
        m = int(math.floor(fe_lon * (nl_val - 1) - fo_lon * nl_val + 0.5))
        rlon = dlon * ((m % ni) + fo_lon)
    else:
        rlat = rlat0
        nl_val = nl0
        ni = max(nl_val, 1)
        dlon = 360.0 / ni
        m = int(math.floor(fe_lon * (nl_val - 1) - fo_lon * nl_val + 0.5))
        rlon = dlon * ((m % ni) + fe_lon)

    if rlon >= 180.0:
        rlon -= 360.0

    return rlat, rlon


# ═══════════════════════════════════════════════════════════════════════
# Velocity decoding (TC 19, subtype 1)
# ═══════════════════════════════════════════════════════════════════════

def decode_velocity(me_int):
    subtype = (me_int >> 48) & 0x7
    if subtype not in (1, 2):
        return None, None, None

    ew_dir = (me_int >> 42) & 1
    ew_vel = (me_int >> 32) & 0x3FF
    ns_dir = (me_int >> 31) & 1
    ns_vel = (me_int >> 21) & 0x3FF

    if ew_vel == 0 or ns_vel == 0:
        return None, None, None

    ew_speed = (ew_vel - 1) * (-1 if ew_dir else 1)
    ns_speed = (ns_vel - 1) * (-1 if ns_dir else 1)

    ground_speed = math.sqrt(ew_speed ** 2 + ns_speed ** 2)
    heading = math.degrees(math.atan2(ew_speed, ns_speed)) % 360.0

    vr_sign_bit = (me_int >> 19) & 1
    vr_val = (me_int >> 10) & 0x1FF
    if vr_val == 0:
        vertical_rate = 0
    else:
        vertical_rate = (vr_val - 1) * 64
        if vr_sign_bit:
            vertical_rate = -vertical_rate

    return round(ground_speed, 1), round(heading, 1), vertical_rate


# ═══════════════════════════════════════════════════════════════════════
# Registry lookup
# ═══════════════════════════════════════════════════════════════════════

def load_registry(db_path):
    """Load the aircraft registry from SQLite."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT icao_hex, registration, operator FROM aircraft_registry")
    registry = {}
    for row in c.fetchall():
        registry[row[0].upper()] = {"registration": row[1], "operator": row[2]}
    conn.close()
    return registry


# ═══════════════════════════════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════════════════════════════

def decode_messages(raw_messages):
    """Decode a list of raw Mode S byte arrays into aircraft data."""
    aircraft = {}

    for msg_bytes in raw_messages:
        # Only process 14-byte (112-bit) long messages
        if len(msg_bytes) != 14:
            continue

        # CRC-24 integrity check
        if crc24_residual(msg_bytes) != 0:
            continue

        # Downlink Format (first 5 bits of first byte)
        df = (msg_bytes[0] >> 3) & 0x1F
        if df != 17:
            continue

        # ICAO address (bytes 1-3)
        icao = msg_bytes[1:4].hex().upper()

        # ME field (bytes 4-10, 56 bits)
        me_int = int.from_bytes(msg_bytes[4:11], "big")

        # Type Code (top 5 bits of ME)
        tc = (me_int >> 51) & 0x1F

        if icao not in aircraft:
            aircraft[icao] = {
                "callsign": None,
                "lat": None,
                "lon": None,
                "altitude_ft": None,
                "ground_speed_kts": None,
                "heading_deg": None,
                "vertical_rate_fpm": None,
                "num_valid_messages": 0,
                "_cpr_even": None,
                "_cpr_odd": None,
            }

        ac = aircraft[icao]
        ac["num_valid_messages"] += 1

        if 1 <= tc <= 4:
            ac["callsign"] = decode_callsign(me_int)

        elif 9 <= tc <= 18:
            alt_code = (me_int >> 36) & 0xFFF
            alt = decode_altitude(alt_code)
            if alt is not None:
                ac["altitude_ft"] = alt

            cpr_format = (me_int >> 34) & 1
            lat_cpr = (me_int >> 17) & 0x1FFFF
            lon_cpr = me_int & 0x1FFFF

            if cpr_format == 0:
                ac["_cpr_even"] = (lat_cpr, lon_cpr)
            else:
                ac["_cpr_odd"] = (lat_cpr, lon_cpr)

            if ac["_cpr_even"] is not None and ac["_cpr_odd"] is not None:
                yz_e, xz_e = ac["_cpr_even"]
                yz_o, xz_o = ac["_cpr_odd"]
                lat, lon = decode_cpr_global(
                    yz_e, xz_e, yz_o, xz_o, use_odd=(cpr_format == 1)
                )
                if lat is not None:
                    ac["lat"] = round(lat, 6)
                    ac["lon"] = round(lon, 6)

        elif tc == 19:
            spd, hdg, vr = decode_velocity(me_int)
            if spd is not None:
                ac["ground_speed_kts"] = spd
                ac["heading_deg"] = hdg
                ac["vertical_rate_fpm"] = vr

    return aircraft


def main():
    bin_path = "/app/station_capture.bin"
    db_path = "/app/registry.db"
    out_path = "/app/aircraft_report.json"

    # Step 1: Parse the binary container
    raw_messages = parse_binary_log(bin_path)
    print(f"Extracted {len(raw_messages)} raw messages from binary log")

    # Step 2: Decode ADS-B messages
    aircraft = decode_messages(raw_messages)
    print(f"Decoded {len(aircraft)} aircraft")

    # Step 3: Cross-reference with registry
    registry = load_registry(db_path)

    # Step 4: Build output report
    report = {}
    for icao, ac in aircraft.items():
        reg_info = registry.get(icao, {})
        report[icao] = {
            "callsign": ac["callsign"],
            "lat": ac["lat"],
            "lon": ac["lon"],
            "altitude_ft": ac["altitude_ft"],
            "ground_speed_kts": ac["ground_speed_kts"],
            "heading_deg": ac["heading_deg"],
            "vertical_rate_fpm": ac["vertical_rate_fpm"],
            "num_valid_messages": ac["num_valid_messages"],
            "registration": reg_info.get("registration"),
            "operator": reg_info.get("operator"),
        }

    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Wrote report to {out_path}")
    for icao, data in sorted(report.items()):
        print(f"  {icao}: {data['callsign'] or '?':8s}  "
              f"reg={data['registration']}  op={data['operator']}  "
              f"lat={data['lat']}  lon={data['lon']}  "
              f"alt={data['altitude_ft']}ft  "
              f"gs={data['ground_speed_kts']}kts  "
              f"hdg={data['heading_deg']}  "
              f"vr={data['vertical_rate_fpm']}fpm  "
              f"({data['num_valid_messages']} msgs)")


if __name__ == "__main__":
    main()
