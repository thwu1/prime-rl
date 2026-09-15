#!/usr/bin/env python3
"""
Multi-station ADS-B track fusion pipeline.
Ingests DF17 hex messages from multiple station files, performs CRC-24
error correction, decodes identification/position/velocity, stores
results in SQLite, and detects spoofed aircraft via kinematic analysis.
"""
import sys
import os
import json
import math
import glob
import sqlite3


# ===== CRC-24 =====

def crc24(msg_bytes):
    """Compute Mode S CRC-24. Valid message -> syndrome 0."""
    crc = 0
    for byte in msg_bytes:
        crc ^= (byte << 16)
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1FFF409
    return crc & 0xFFFFFF


def build_syndrome_table():
    """Map each single-bit-error syndrome to its bit position (0..111)."""
    table = {}
    for bit in range(112):
        msg = bytearray(14)
        byte_idx = bit // 8
        bit_idx = 7 - (bit % 8)
        msg[byte_idx] = 1 << bit_idx
        syndrome = crc24(bytes(msg))
        table[syndrome] = bit
    return table


# ===== Callsign decoding =====

def decode_callsign(me):
    """Decode 8-character callsign from ME bytes (TC 1-4)."""
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


# ===== Altitude decoding =====

def decode_altitude(me):
    """Decode barometric altitude from ME bytes (TC 9-18). Returns feet or None."""
    alt_code = ((me[1] << 4) | (me[2] >> 4)) & 0xFFF
    q_bit = (alt_code >> 4) & 1
    if q_bit == 1:
        n = ((alt_code >> 5) << 4) | (alt_code & 0x0F)
        return n * 25 - 1000
    return None


# ===== CPR decoding =====

def nl_func(lat):
    """NL: number of longitude zones for CPR."""
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
    """
    CPR global unambiguous decode from even/odd pair.
    Even frame treated as most recent.
    Returns (lat, lon) or None if ambiguous.
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
    lon = d_lon * ((m % n_even) + lon_even_frac)

    if lon >= 180.0:
        lon -= 360.0

    return lat, lon


# ===== Velocity decoding =====

def decode_velocity(me):
    """Decode airborne velocity from ME bytes (TC 19, ST 1/2)."""
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
    heading = math.degrees(math.atan2(vew, vns)) % 360.0

    vr = 0
    if vr_enc > 0:
        vr = (vr_enc - 1) * 64
        if svr == 1:
            vr = -vr

    return {
        'gs': round(gs, 2),
        'hdg': round(heading, 2),
        'vr': vr
    }


# ===== Distance computation =====

def haversine_nm(lat1, lon1, lat2, lon2):
    """Great-circle distance in nautical miles."""
    R_nm = 3440.065
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R_nm * c


# ===== Main pipeline =====

def main(station_dir, db_path, report_path):
    # Build syndrome table for error correction
    syn_table = build_syndrome_table()

    # Find station hex files
    hex_files = sorted(glob.glob(os.path.join(station_dir, '*.hex')))
    if not hex_files:
        print("No .hex files found", file=sys.stderr)
        sys.exit(1)

    # Create database
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    conn.executescript("""
        DROP TABLE IF EXISTS velocities;
        DROP TABLE IF EXISTS positions;
        DROP TABLE IF EXISTS aircraft;
        DROP TABLE IF EXISTS raw_messages;
        CREATE TABLE raw_messages (
            msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL,
            hex_raw TEXT NOT NULL,
            crc_syndrome INTEGER,
            status TEXT NOT NULL,
            corrected_hex TEXT,
            df INTEGER,
            icao TEXT,
            type_code INTEGER
        );
        CREATE TABLE aircraft (
            icao TEXT PRIMARY KEY,
            callsign TEXT
        );
        CREATE TABLE positions (
            pos_id INTEGER PRIMARY KEY AUTOINCREMENT,
            icao TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            altitude INTEGER,
            source_station TEXT,
            FOREIGN KEY (icao) REFERENCES aircraft(icao)
        );
        CREATE TABLE velocities (
            vel_id INTEGER PRIMARY KEY AUTOINCREMENT,
            icao TEXT NOT NULL,
            ground_speed REAL,
            heading REAL,
            vertical_rate INTEGER,
            source_station TEXT,
            FOREIGN KEY (icao) REFERENCES aircraft(icao)
        );
    """)

    # Track state across all stations
    all_hex_set = set()
    total_messages = 0
    corrected_count = 0
    invalid_count = 0

    # Per-aircraft tracking
    aircraft_data = {}  # icao -> {callsign, positions, velocities, stations, cpr_state}

    def ensure_aircraft(icao_str):
        if icao_str not in aircraft_data:
            aircraft_data[icao_str] = {
                'callsign': None,
                'positions': [],
                'velocities': [],
                'stations': set(),
                '_cpr_even': None,
                '_cpr_odd': None,
            }

    # Process each station
    for hex_file in hex_files:
        station_id = os.path.splitext(os.path.basename(hex_file))[0]

        with open(hex_file) as f:
            lines = [line.strip() for line in f if line.strip()]

        for hex_line in lines:
            total_messages += 1
            all_hex_set.add(hex_line)

            # Parse hex
            try:
                msg = bytes.fromhex(hex_line)
            except ValueError:
                invalid_count += 1
                conn.execute(
                    "INSERT INTO raw_messages (station_id, hex_raw, crc_syndrome, "
                    "status, corrected_hex, df, icao, type_code) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (station_id, hex_line, None, 'invalid', None, None, None, None)
                )
                continue

            if len(msg) != 14:
                invalid_count += 1
                conn.execute(
                    "INSERT INTO raw_messages (station_id, hex_raw, crc_syndrome, "
                    "status, corrected_hex, df, icao, type_code) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (station_id, hex_line, None, 'invalid', None, None, None, None)
                )
                continue

            syndrome = crc24(msg)
            corrected = False
            corrected_hex = None

            if syndrome == 0:
                status = 'valid'
            elif syndrome in syn_table:
                bit = syn_table[syndrome]
                msg = bytearray(msg)
                byte_idx = bit // 8
                bit_idx = 7 - (bit % 8)
                msg[byte_idx] ^= (1 << bit_idx)
                msg = bytes(msg)
                corrected = True
                corrected_hex = msg.hex().upper()
                corrected_count += 1
                status = 'corrected'
            else:
                invalid_count += 1
                status = 'invalid'

            # Extract DF, ICAO, TC for the database
            df = (msg[0] >> 3) & 0x1F
            icao_str = None
            tc = None

            if status != 'invalid' and df == 17:
                icao = (msg[1] << 16) | (msg[2] << 8) | msg[3]
                icao_str = format(icao, '06X')
                me = msg[4:11]
                tc = (me[0] >> 3) & 0x1F

            conn.execute(
                "INSERT INTO raw_messages (station_id, hex_raw, crc_syndrome, "
                "status, corrected_hex, df, icao, type_code) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (station_id, hex_line, syndrome, status, corrected_hex,
                 df if status != 'invalid' else None,
                 icao_str, tc)
            )

            if status == 'invalid':
                continue

            if df != 17:
                continue

            # Decode DF17 message
            ensure_aircraft(icao_str)
            ac = aircraft_data[icao_str]
            ac['stations'].add(station_id)

            if 1 <= tc <= 4:
                # Identification
                cs = decode_callsign(me)
                ac['callsign'] = cs
                conn.execute(
                    "INSERT OR REPLACE INTO aircraft (icao, callsign) VALUES (?,?)",
                    (icao_str, cs)
                )

            elif 9 <= tc <= 18:
                # Airborne position
                alt = decode_altitude(me)
                fflag = (me[2] >> 2) & 0x01
                lat_cpr = ((me[2] & 0x03) << 15) | (me[3] << 7) | (me[4] >> 1)
                lon_cpr = ((me[4] & 0x01) << 16) | (me[5] << 8) | me[6]

                if fflag == 0:
                    ac['_cpr_even'] = (lat_cpr, lon_cpr, alt, station_id)
                else:
                    ac['_cpr_odd'] = (lat_cpr, lon_cpr, alt, station_id)

                if ac['_cpr_even'] is not None and ac['_cpr_odd'] is not None:
                    result = cpr_global_decode(
                        ac['_cpr_even'][0], ac['_cpr_odd'][0],
                        ac['_cpr_even'][1], ac['_cpr_odd'][1]
                    )
                    if result is not None:
                        lat, lon = result
                        src_station = ac['_cpr_even'][3]
                        pos = {
                            'lat': round(lat, 6),
                            'lon': round(lon, 6),
                            'alt': ac['_cpr_even'][2]
                        }
                        ac['positions'].append(pos)
                        conn.execute(
                            "INSERT INTO positions "
                            "(icao, latitude, longitude, altitude, source_station) "
                            "VALUES (?,?,?,?,?)",
                            (icao_str, pos['lat'], pos['lon'], pos['alt'],
                             src_station)
                        )
                    ac['_cpr_even'] = None
                    ac['_cpr_odd'] = None

                # Ensure aircraft is in the aircraft table even without callsign
                conn.execute(
                    "INSERT OR IGNORE INTO aircraft (icao, callsign) VALUES (?,?)",
                    (icao_str, ac['callsign'])
                )

            elif tc == 19:
                vel = decode_velocity(me)
                if vel is not None:
                    ac['velocities'].append(vel)
                    conn.execute(
                        "INSERT INTO velocities "
                        "(icao, ground_speed, heading, vertical_rate, source_station) "
                        "VALUES (?,?,?,?,?)",
                        (icao_str, vel['gs'], vel['hdg'], vel['vr'], station_id)
                    )

                conn.execute(
                    "INSERT OR IGNORE INTO aircraft (icao, callsign) VALUES (?,?)",
                    (icao_str, ac['callsign'])
                )

    conn.commit()
    conn.close()

    # ===== Anomaly detection =====
    DISTANCE_THRESHOLD_NM = 100.0  # Any consecutive jump > 100nm is anomalous
    spoofed_icao = None
    max_distance = 0

    for icao_str, ac in aircraft_data.items():
        ac['anomaly'] = False
        positions = ac['positions']
        if len(positions) >= 2:
            for i in range(len(positions) - 1):
                p1 = positions[i]
                p2 = positions[i + 1]
                dist = haversine_nm(p1['lat'], p1['lon'], p2['lat'], p2['lon'])
                if dist > DISTANCE_THRESHOLD_NM:
                    ac['anomaly'] = True
                    if dist > max_distance:
                        max_distance = dist
                        spoofed_icao = icao_str

    # ===== Build report =====
    report_aircraft = {}
    for icao_str, ac in aircraft_data.items():
        report_aircraft[icao_str] = {
            'callsign': ac['callsign'],
            'positions': ac['positions'],
            'velocities': ac['velocities'],
            'stations': sorted(ac['stations']),
            'anomaly': ac['anomaly'],
        }

    report = {
        'aircraft': report_aircraft,
        'stats': {
            'total_messages': total_messages,
            'unique_messages': len(all_hex_set),
            'corrected_messages': corrected_count,
            'invalid_messages': invalid_count,
            'aircraft_count': len(aircraft_data),
            'spoofed_icao': spoofed_icao,
        }
    }

    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <station_dir> <db_path> <report_path>",
              file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
