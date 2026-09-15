#!/usr/bin/env python3
"""ADS-B Mode S DF17 decoder with CRC-24 error correction and CPR position decoding."""

import math
import json

GENERATOR = 0x1FFF409


def crc24(msg_bytes):
    n_bytes = len(msg_bytes)
    msg_int = int.from_bytes(msg_bytes, 'big')
    nbits = n_bytes * 8
    for i in range(nbits - 24):
        if msg_int & (1 << (nbits - 1 - i)):
            msg_int ^= GENERATOR << (nbits - 25 - i)
    return msg_int & 0xFFFFFF


def crc24_hex(hex_str):
    return crc24(bytes.fromhex(hex_str))


def build_syndrome_table(msg_bits=112):
    table = {}
    for bit in range(msg_bits):
        err = bytearray(msg_bits // 8)
        byte_idx = bit // 8
        bit_idx = 7 - (bit % 8)
        err[byte_idx] = 1 << bit_idx
        syndrome = crc24(bytes(err))
        table[syndrome] = bit
    return table


def correct_single_bit(msg_hex, syndrome_table):
    syndrome = crc24_hex(msg_hex)
    if syndrome == 0:
        return msg_hex, None
    if syndrome in syndrome_table:
        bit_pos = syndrome_table[syndrome]
        msg_int = int(msg_hex, 16)
        nbits = len(msg_hex) * 4
        msg_int ^= (1 << (nbits - 1 - bit_pos))
        corrected = format(msg_int, '0' + str(len(msg_hex)) + 'X')
        if crc24_hex(corrected) == 0:
            return corrected, bit_pos
    return None, None


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


Nb = 17
NZ_CPR = 15


def cpr_global_decode(lat_cpr_even, lon_cpr_even, lat_cpr_odd, lon_cpr_odd, latest_even=True):
    dlat0 = 360.0 / (4 * NZ_CPR)
    dlat1 = 360.0 / (4 * NZ_CPR - 1)

    lat_cpr_even_f = lat_cpr_even / (2 ** Nb)
    lon_cpr_even_f = lon_cpr_even / (2 ** Nb)
    lat_cpr_odd_f = lat_cpr_odd / (2 ** Nb)
    lon_cpr_odd_f = lon_cpr_odd / (2 ** Nb)

    j = math.floor(59 * lat_cpr_even_f - 60 * lat_cpr_odd_f + 0.5)

    lat_even = dlat0 * ((j % 60) + lat_cpr_even_f)
    lat_odd = dlat1 * ((j % 59) + lat_cpr_odd_f)

    if lat_even >= 270:
        lat_even -= 360
    if lat_odd >= 270:
        lat_odd -= 360

    if NL(lat_even) != NL(lat_odd):
        return None

    if latest_even:
        lat = lat_even
        nl = NL(lat)
        ni = max(nl, 1)
        dlon = 360.0 / ni
        m = math.floor(lon_cpr_even_f * (nl - 1) - lon_cpr_odd_f * nl + 0.5)
        lon = dlon * ((m % ni) + lon_cpr_even_f)
    else:
        lat = lat_odd
        nl = NL(lat)
        ni = max(nl - 1, 1)
        dlon = 360.0 / ni
        m = math.floor(lon_cpr_even_f * (nl - 1) - lon_cpr_odd_f * nl + 0.5)
        lon = dlon * ((m % ni) + lon_cpr_odd_f)

    if lon >= 180:
        lon -= 360

    return lat, lon


def decode_altitude(alt12):
    q_bit = (alt12 >> 4) & 1
    if q_bit == 1:
        upper = (alt12 >> 5) & 0x7F
        lower = alt12 & 0x0F
        N = (upper << 4) | lower
        return N * 25 - 1000
    return None


CHARSET = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### #####0123456789######"


def decode_callsign(bits48):
    cs = ""
    for i in range(8):
        idx = (bits48 >> (42 - 6 * i)) & 0x3F
        if idx < len(CHARSET):
            cs += CHARSET[idx]
        else:
            cs += "?"
    return cs.rstrip()


def decode_velocity(me):
    tc = (me >> 51) & 0x1F
    st = (me >> 48) & 0x07
    if tc != 19 or st not in (1, 2):
        return None

    ew_dir = (me >> 42) & 1
    ew_vel = (me >> 32) & 0x3FF
    ns_dir = (me >> 31) & 1
    ns_vel = (me >> 21) & 0x3FF
    vr_sign = (me >> 19) & 1
    vr = (me >> 10) & 0x1FF

    v_ew = (ew_vel - 1) * (-1 if ew_dir else 1)
    v_ns = (ns_vel - 1) * (-1 if ns_dir else 1)

    gs = math.sqrt(v_ew ** 2 + v_ns ** 2)
    hdg = math.degrees(math.atan2(v_ew, v_ns))
    if hdg < 0:
        hdg += 360

    vrate = (vr - 1) * 64 * (-1 if vr_sign else 1)

    return {
        "ground_speed": round(gs, 2),
        "heading": round(hdg, 2),
        "vertical_rate": vrate,
    }


def haversine(lat1, lon1, lat2, lon2):
    R = 3440.065
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def main():
    input_path = "/app/messages.txt"
    output_path = "/app/output.json"

    syndrome_table = build_syndrome_table(112)

    with open(input_path) as f:
        raw_lines = [line.strip() for line in f if line.strip()]

    total_messages = 0
    valid_messages = 0
    corrected_messages = 0
    aircraft = {}

    for line in raw_lines:
        if line.startswith("*") and line.endswith(";"):
            hex_msg = line[1:-1].upper()
        else:
            continue

        if len(hex_msg) != 28:
            continue

        total_messages += 1
        crc_val = crc24_hex(hex_msg)

        if crc_val != 0:
            fixed, bit_pos = correct_single_bit(hex_msg, syndrome_table)
            if fixed:
                hex_msg = fixed
                corrected_messages += 1
            else:
                continue
        else:
            valid_messages += 1

        msg_bytes = bytes.fromhex(hex_msg)
        df = (msg_bytes[0] >> 3) & 0x1F

        if df != 17:
            continue

        icao = format(int.from_bytes(msg_bytes[1:4], 'big'), '06X')
        me = int.from_bytes(msg_bytes[4:11], 'big')
        tc = (me >> 51) & 0x1F

        if icao not in aircraft:
            aircraft[icao] = {
                "callsign": None,
                "position": {"lat": None, "lon": None},
                "altitude": None,
                "velocity": None,
                "cpr_even": None,
                "cpr_odd": None,
            }

        ac = aircraft[icao]

        if 1 <= tc <= 4:
            cs_bits = me & ((1 << 48) - 1)
            ac["callsign"] = decode_callsign(cs_bits)
        elif 9 <= tc <= 18:
            alt12 = (me >> 36) & 0xFFF
            flag = (me >> 34) & 1
            lat_cpr = (me >> 17) & 0x1FFFF
            lon_cpr = me & 0x1FFFF
            ac["altitude"] = decode_altitude(alt12)
            if flag == 0:
                ac["cpr_even"] = (lat_cpr, lon_cpr)
            else:
                ac["cpr_odd"] = (lat_cpr, lon_cpr)
        elif tc == 19:
            vel = decode_velocity(me)
            if vel:
                ac["velocity"] = vel

    for icao, ac in aircraft.items():
        if ac["cpr_even"] and ac["cpr_odd"]:
            pos = cpr_global_decode(
                ac["cpr_even"][0], ac["cpr_even"][1],
                ac["cpr_odd"][0], ac["cpr_odd"][1],
                latest_even=True,
            )
            if pos is None:
                pos = cpr_global_decode(
                    ac["cpr_even"][0], ac["cpr_even"][1],
                    ac["cpr_odd"][0], ac["cpr_odd"][1],
                    latest_even=False,
                )
            if pos:
                ac["position"]["lat"] = round(pos[0], 4)
                ac["position"]["lon"] = round(pos[1], 4)

    icao_list = list(aircraft.keys())
    min_dist = float("inf")
    closest_pair = (None, None)

    for i in range(len(icao_list)):
        for j in range(i + 1, len(icao_list)):
            a1 = aircraft[icao_list[i]]
            a2 = aircraft[icao_list[j]]
            if a1["position"]["lat"] is not None and a2["position"]["lat"] is not None:
                dist = haversine(
                    a1["position"]["lat"], a1["position"]["lon"],
                    a2["position"]["lat"], a2["position"]["lon"],
                )
                if dist < min_dist:
                    min_dist = dist
                    pair = sorted([icao_list[i], icao_list[j]])
                    closest_pair = (pair[0], pair[1])

    output_aircraft = {}
    for icao, ac in aircraft.items():
        output_aircraft[icao] = {
            "callsign": ac["callsign"] or "",
            "position": ac["position"],
            "altitude": ac["altitude"],
            "velocity": ac["velocity"] or {"ground_speed": 0, "heading": 0, "vertical_rate": 0},
        }

    result = {
        "aircraft": output_aircraft,
        "statistics": {
            "total_messages": total_messages,
            "valid_messages": valid_messages,
            "corrected_messages": corrected_messages,
            "unique_aircraft": len(aircraft),
        },
        "closest_pair": {
            "aircraft_1": closest_pair[0],
            "aircraft_2": closest_pair[1],
            "distance_nm": round(min_dist, 2) if min_dist != float("inf") else None,
        },
    }

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Decoded {len(aircraft)} aircraft from {total_messages} messages")
    print(f"  Valid: {valid_messages}, Corrected: {corrected_messages}")
    if closest_pair[0]:
        print(f"  Closest pair: {closest_pair[0]}-{closest_pair[1]}: {min_dist:.2f} NM")
    print(f"Output written to {output_path}")


if __name__ == "__main__":
    main()
