#!/usr/bin/env python3
"""
ADS-B Mode S DF17 Message Encoder with round-trip validation.

"""

import sqlite3
import json
import math
import subprocess
import sys

GENERATOR = 0x1FFF409


def crc24(msg_bytes):
    n_bytes = len(msg_bytes)
    msg_int = int.from_bytes(msg_bytes, 'big')
    nbits = n_bytes * 8
    for i in range(nbits - 24):
        if msg_int & (1 << (nbits - 1 - i)):
            msg_int ^= GENERATOR << (nbits - 25 - i)
    return msg_int & 0xFFFFFF


def append_crc24(msg_hex_11bytes):
    padded = msg_hex_11bytes + "000000"
    crc = crc24(bytes.fromhex(padded))
    return msg_hex_11bytes + format(crc, '06X')


def NL(lat):
    lat = abs(lat)
    if lat == 0:
        return 59
    if lat >= 87.0:
        return 1
    NZ = 15
    a = 1 - math.cos(math.pi / (2 * NZ))
    b = math.cos(math.pi * lat / 180.0) ** 2
    nl = math.floor(2 * math.pi / math.acos(1 - a / b))
    return nl


CHARSET = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### #####0123456789######"


def encode_callsign_bits(callsign):
    padded = callsign.ljust(8)[:8]
    bits48 = 0
    for ch in padded:
        idx = CHARSET.find(ch)
        if idx < 0:
            idx = 32
        bits48 = (bits48 << 6) | idx
    return bits48


def encode_altitude(alt_ft):
    N = (alt_ft + 1000) // 25
    upper = (N >> 4) & 0x7F
    lower = N & 0x0F
    alt12 = (upper << 5) | (1 << 4) | lower
    return alt12


def cpr_encode(lat, lon, is_odd):
    NZ = 15
    Nb = 17

    dlat = 360.0 / (4 * NZ - (1 if is_odd else 0))

    lat_norm = lat if lat >= 0 else lat + 360

    yz = math.floor(((lat_norm % dlat) / dlat) * (2 ** Nb) + 0.5)
    yz &= (2 ** Nb - 1)

    nl = NL(lat)
    ni = max(nl - (1 if is_odd else 0), 1)
    dlon = 360.0 / ni

    lon_norm = lon if lon >= 0 else lon + 360

    xz = math.floor(((lon_norm % dlon) / dlon) * (2 ** Nb) + 0.5)
    xz &= (2 ** Nb - 1)

    return yz, xz


def build_ident_me(callsign):
    tc = 4
    ec = 0
    cs_bits = encode_callsign_bits(callsign)
    return (tc << 51) | (ec << 48) | cs_bits


def build_position_me(alt_ft, lat, lon, is_odd):
    tc = 11
    alt12 = encode_altitude(alt_ft)
    flag = 1 if is_odd else 0
    lat_cpr, lon_cpr = cpr_encode(lat, lon, is_odd)

    me = 0
    me |= (tc & 0x1F) << 51
    me |= (alt12 & 0xFFF) << 36
    me |= (flag & 1) << 34
    me |= (lat_cpr & 0x1FFFF) << 17
    me |= (lon_cpr & 0x1FFFF)
    return me


def build_velocity_me(ground_speed, heading_deg, vertical_rate):
    heading_rad = math.radians(heading_deg)
    v_ew = ground_speed * math.sin(heading_rad)
    v_ns = ground_speed * math.cos(heading_rad)

    ew_dir = 1 if v_ew < 0 else 0
    ew_vel = min(int(round(abs(v_ew))) + 1, 1023)
    ns_dir = 1 if v_ns < 0 else 0
    ns_vel = min(int(round(abs(v_ns))) + 1, 1023)

    vr_sign = 1 if vertical_rate < 0 else 0
    vr = min(abs(vertical_rate) // 64 + 1, 511)

    me = 0
    me |= (19 & 0x1F) << 51
    me |= (1 & 0x07) << 48
    me |= (ew_dir & 1) << 42
    me |= (ew_vel & 0x3FF) << 32
    me |= (ns_dir & 1) << 31
    me |= (ns_vel & 0x3FF) << 21
    me |= (vr_sign & 1) << 19
    me |= (vr & 0x1FF) << 10
    return me


def build_message(icao_hex, me):
    first_byte = 0x8D
    icao_int = int(icao_hex, 16)
    msg_no_crc = format(first_byte, '02X') + format(icao_int, '06X') + format(me, '014X')
    return append_crc24(msg_no_crc)


def inject_bit_error(msg_hex, bit_pos):
    msg_int = int(msg_hex, 16)
    nbits = len(msg_hex) * 4
    msg_int ^= (1 << (nbits - 1 - bit_pos))
    return format(msg_int, '0' + str(len(msg_hex)) + 'X')


def main():
    db = sqlite3.connect("/app/aircraft.db")
    db.row_factory = sqlite3.Row

    rows = db.execute("""
        SELECT a.icao, a.callsign,
               p.latitude, p.longitude, p.altitude_ft,
               v.ground_speed_kt, v.heading_deg, v.vertical_rate_fpm
        FROM aircraft a
        JOIN positions p ON a.icao = p.icao
        JOIN velocities v ON a.icao = v.icao
        ORDER BY a.icao
    """).fetchall()

    errors = {}
    for row in db.execute("SELECT icao, message_type, bit_position FROM error_injection"):
        errors[(row["icao"], row["message_type"])] = row["bit_position"]

    db.close()

    messages = []
    for row in rows:
        icao = row["icao"]
        cs = row["callsign"]
        lat = row["latitude"]
        lon = row["longitude"]
        alt = row["altitude_ft"]
        gs = row["ground_speed_kt"]
        hdg = row["heading_deg"]
        vr = row["vertical_rate_fpm"]

        ident_msg = build_message(icao, build_ident_me(cs))
        if (icao, "identification") in errors:
            ident_msg = inject_bit_error(ident_msg, errors[(icao, "identification")])
        messages.append(ident_msg)

        pos_even_msg = build_message(icao, build_position_me(alt, lat, lon, is_odd=False))
        if (icao, "position_even") in errors:
            pos_even_msg = inject_bit_error(pos_even_msg, errors[(icao, "position_even")])
        messages.append(pos_even_msg)

        pos_odd_msg = build_message(icao, build_position_me(alt, lat, lon, is_odd=True))
        if (icao, "position_odd") in errors:
            pos_odd_msg = inject_bit_error(pos_odd_msg, errors[(icao, "position_odd")])
        messages.append(pos_odd_msg)

        vel_msg = build_message(icao, build_velocity_me(gs, hdg, vr))
        if (icao, "velocity") in errors:
            vel_msg = inject_bit_error(vel_msg, errors[(icao, "velocity")])
        messages.append(vel_msg)

    with open("/app/messages.txt", "w") as f:
        for msg in messages:
            f.write(f"*{msg};\n")

    print(f"Encoded {len(messages)} messages for {len(rows)} aircraft")

    result = subprocess.run(
        ["python3", "/app/decoder.py"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Decoder failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(result.stdout)

    with open("/app/output.json") as f:
        decoded = json.load(f)

    db = sqlite3.connect("/app/aircraft.db")
    db.row_factory = sqlite3.Row
    rows = db.execute("""
        SELECT a.icao, a.callsign,
               p.latitude, p.longitude, p.altitude_ft,
               v.ground_speed_kt, v.heading_deg, v.vertical_rate_fpm
        FROM aircraft a
        JOIN positions p ON a.icao = p.icao
        JOIN velocities v ON a.icao = v.icao
    """).fetchall()
    error_count = db.execute("SELECT COUNT(*) FROM error_injection").fetchone()[0]
    db.close()

    round_trip = {}
    successful = 0

    for row in rows:
        icao = row["icao"]
        if icao not in decoded["aircraft"]:
            round_trip[icao] = {
                "callsign_match": False,
                "position_error_deg": 999.0,
                "altitude_match": False,
                "velocity_error_kt": 999.0,
                "heading_error_deg": 999.0,
            }
            continue

        ac = decoded["aircraft"][icao]
        cs_match = ac["callsign"].strip() == row["callsign"]

        pos_err = math.sqrt(
            (ac["position"]["lat"] - row["latitude"]) ** 2 +
            (ac["position"]["lon"] - row["longitude"]) ** 2
        )

        alt_match = ac["altitude"] == row["altitude_ft"]

        gs_err = abs(ac["velocity"]["ground_speed"] - row["ground_speed_kt"])

        hdg_err = abs(ac["velocity"]["heading"] - row["heading_deg"])
        if hdg_err > 180:
            hdg_err = 360 - hdg_err

        round_trip[icao] = {
            "callsign_match": cs_match,
            "position_error_deg": round(pos_err, 6),
            "altitude_match": alt_match,
            "velocity_error_kt": round(gs_err, 2),
            "heading_error_deg": round(hdg_err, 2),
        }

        if cs_match and pos_err < 0.05 and alt_match and hdg_err < 1.0:
            successful += 1

    validation = {
        "round_trip_results": round_trip,
        "summary": {
            "total_aircraft": len(rows),
            "total_messages": len(messages),
            "successful_round_trips": successful,
            "error_injected_messages": error_count,
            "error_corrected_messages": decoded["statistics"]["corrected_messages"],
        },
    }

    with open("/app/validation.json", "w") as f:
        json.dump(validation, f, indent=2)

    print(f"Validation: {successful}/{len(rows)} successful round trips")


if __name__ == "__main__":
    main()
