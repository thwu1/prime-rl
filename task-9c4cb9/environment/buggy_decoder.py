#!/usr/bin/env python3
"""ADS-B Mode S DF17 message decoder."""
import sys
import json
import math


def crc24(msg_bytes):
    """Compute CRC-24 checksum over the message."""
    crc = 0
    for byte in msg_bytes:
        crc ^= (byte << 16)
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1FFF409
    return crc & 0xFFFFFF


def decode_callsign(me):
    """Decode callsign from identification ME field."""
    val = int.from_bytes(me, 'big')
    chars = []
    for i in range(8):
        code = (val >> (42 - i * 6)) & 0x3F
        if 1 <= code <= 26:
            chars.append(chr(ord('A') + code - 1))
        elif code == 32:
            chars.append(' ')
        elif 48 <= code <= 57:
            chars.append(chr(ord('0') + code - 48))
        else:
            chars.append(' ')
    return ''.join(chars).rstrip()


def decode_altitude(me):
    """Decode barometric altitude from position ME field."""
    alt_code = ((me[1] << 4) | (me[2] >> 4)) & 0xFFF
    q_bit = (alt_code >> 4) & 1
    if q_bit == 1:
        n = ((alt_code >> 5) << 4) | (alt_code & 0x0F)
        return n * 25 + 1000
    return None


def nl_func(lat):
    """Number of longitude zones for CPR decoding."""
    lat = abs(lat)
    if lat >= 87.0:
        return 1
    if lat < 1e-14:
        return 60
    nz = 15
    a = 1 - math.cos(math.pi / (2 * nz))
    b = math.cos(math.pi * lat / 180.0) ** 2
    val = 1 - a / b
    if val < -1 or val > 1:
        return 1
    return int(math.floor(2 * math.pi / math.acos(val)))


def cpr_global_decode(lat_cpr_even, lat_cpr_odd, lon_cpr_even, lon_cpr_odd):
    """CPR global position decoding from even/odd frame pair.
    Even frame treated as most recent.
    """
    nz = 15
    d_lat_even = 360.0 / (4 * nz)
    d_lat_odd = 360.0 / (4 * nz - 1)

    lat_even_frac = lat_cpr_even / 2**17
    lat_odd_frac = lat_cpr_odd / 2**17

    j = math.floor(59 * lat_even_frac - 60 * lat_odd_frac + 0.5)

    lat_even = d_lat_even * ((j % 60) + lat_even_frac)
    lat_odd = d_lat_odd * ((j % 59) + lat_odd_frac)

    if lat_even >= 270.0:
        lat_even -= 360.0
    if lat_odd >= 270.0:
        lat_odd -= 360.0

    if nl_func(lat_even) != nl_func(lat_odd):
        return None

    lat = lat_even
    nl = nl_func(lat)

    lon_even_frac = lon_cpr_even / 2**17
    lon_odd_frac = lon_cpr_odd / 2**17

    m = math.floor(lon_even_frac * (nl - 1) - lon_odd_frac * nl + 0.5)

    n_even = max(nl, 1)
    d_lon = 360.0 / n_even
    lon = d_lon * ((m % n_even) + lon_odd_frac)

    if lon >= 180.0:
        lon -= 360.0

    return lat, lon


def decode_velocity(me):
    """Decode airborne velocity from ME field (TC 19)."""
    st = me[0] & 0x07
    if st not in (1, 2):
        return None

    dew = (me[1] >> 2) & 0x01
    vew_enc = ((me[1] & 0x03) << 8) | me[2]
    dns = (me[3] >> 7) & 0x01
    vns_enc = ((me[3] & 0x7F) << 3) | (me[4] >> 5)
    svr = (me[4] >> 3) & 0x01
    vr_enc = ((me[4] & 0x07) << 6) | (me[5] >> 2)

    if vew_enc == 0 or vns_enc == 0:
        return None

    vew = vew_enc - 1
    vns = vns_enc - 1

    if dew == 1:
        vew = -vew
    if dns == 1:
        vns = -vns

    gs = math.sqrt(vew**2 + vns**2)
    heading = math.degrees(math.atan2(vns, vew)) % 360.0

    vr = 0
    if vr_enc > 0:
        vr = (vr_enc - 1) * 64
        if svr == 1:
            vr = -vr

    return {
        'ground_speed': round(gs, 2),
        'heading': round(heading, 2),
        'vertical_rate': vr
    }


def decode(input_file, output_file):
    with open(input_file) as f:
        hex_messages = [line.strip() for line in f if line.strip()]

    aircraft = {}
    stats = {
        'total_messages': len(hex_messages),
        'valid_messages': 0,
        'corrected_messages': 0,
        'invalid_messages': 0,
    }

    for hex_msg in hex_messages:
        try:
            msg = bytes.fromhex(hex_msg)
        except ValueError:
            stats['invalid_messages'] += 1
            continue

        if len(msg) != 14:
            stats['invalid_messages'] += 1
            continue

        syndrome = crc24(msg)

        if syndrome != 0:
            stats['invalid_messages'] += 1
            continue

        stats['valid_messages'] += 1

        df = (msg[0] >> 3) & 0x1F
        if df != 17:
            continue

        icao = (msg[1] << 16) | (msg[2] << 8) | msg[3]
        icao_str = format(icao, '06X')
        me = msg[4:11]
        tc = (me[0] >> 3) & 0x1F

        if icao_str not in aircraft:
            aircraft[icao_str] = {
                'callsign': None,
                'positions': [],
                'velocities': [],
                '_cpr_even': None,
                '_cpr_odd': None,
            }

        ac = aircraft[icao_str]

        if 1 <= tc <= 4:
            ac['callsign'] = decode_callsign(me)

        elif 9 <= tc <= 18:
            alt = decode_altitude(me)
            fflag = (me[2] >> 2) & 0x01
            lat_cpr = ((me[2] & 0x03) << 15) | (me[3] << 7) | (me[4] >> 1)
            lon_cpr = ((me[4] & 0x01) << 16) | (me[5] << 8) | me[6]

            if fflag == 0:
                ac['_cpr_even'] = (lat_cpr, lon_cpr, alt)
            else:
                ac['_cpr_odd'] = (lat_cpr, lon_cpr, alt)

            if ac['_cpr_even'] is not None and ac['_cpr_odd'] is not None:
                result = cpr_global_decode(
                    ac['_cpr_even'][0], ac['_cpr_odd'][0],
                    ac['_cpr_even'][1], ac['_cpr_odd'][1]
                )
                if result is not None:
                    lat, lon = result
                    ac['positions'].append({
                        'latitude': round(lat, 6),
                        'longitude': round(lon, 6),
                        'altitude': ac['_cpr_even'][2],
                    })
                ac['_cpr_even'] = None
                ac['_cpr_odd'] = None

        elif tc == 19:
            vel = decode_velocity(me)
            if vel is not None:
                ac['velocities'].append(vel)

    for icao_str in aircraft:
        aircraft[icao_str].pop('_cpr_even', None)
        aircraft[icao_str].pop('_cpr_odd', None)

    result = {
        'aircraft': aircraft,
        'stats': stats,
    }

    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_hex_file> <output_json_file>",
              file=sys.stderr)
        sys.exit(1)
    decode(sys.argv[1], sys.argv[2])
