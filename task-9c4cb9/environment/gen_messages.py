#!/usr/bin/env python3
"""
Generate ADS-B Mode S test messages for the decoder task.
Creates /app/messages.hex with encoded DF17 messages including
valid messages, messages with single-bit errors, and uncorrectable messages.
"""
import math
import os

def crc24(data):
    """Compute Mode S CRC-24 over a bytes object."""
    crc = 0
    for byte in data:
        crc ^= (byte << 16)
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1FFF409
    return crc & 0xFFFFFF

def nl_func(lat):
    """Number of longitude zones for CPR encoding."""
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

def encode_char(ch):
    """Encode a character to 6-bit ADS-B callsign code."""
    if 'A' <= ch <= 'Z':
        return ord(ch) - ord('A') + 1
    if ch == ' ':
        return 32
    if '0' <= ch <= '9':
        return ord(ch) - ord('0') + 48
    return 32

def encode_callsign(cs):
    """Encode 8-character callsign to 48 bits."""
    padded = (cs + '        ')[:8]
    bits = 0
    for ch in padded:
        bits = (bits << 6) | (encode_char(ch) & 0x3F)
    return bits

def make_id_me(tc, ec, callsign):
    """Create ME field (7 bytes) for aircraft identification."""
    cs_bits = encode_callsign(callsign)
    me = ((tc & 0x1F) << 51) | ((ec & 0x07) << 48) | (cs_bits & 0xFFFFFFFFFFFF)
    return me.to_bytes(7, 'big')

def encode_altitude(alt_ft):
    """Encode altitude using Q-bit method (25ft resolution)."""
    n = (alt_ft + 1000) // 25
    upper = (n >> 4) & 0x7F
    lower = n & 0x0F
    alt_code = (upper << 5) | (1 << 4) | lower
    return alt_code

def cpr_encode(lat, lon, fflag):
    """Encode lat/lon to 17-bit CPR values. fflag: 0=even, 1=odd."""
    nz = 15
    d_lat = 360.0 / (4 * nz - fflag)
    yz = math.floor(2**17 * ((lat % d_lat) / d_lat) + 0.5)
    lat_cpr = yz % (2**17)

    nl = nl_func(lat)
    n_lon = max(nl - fflag, 1)
    d_lon = 360.0 / n_lon
    xz = math.floor(2**17 * ((lon % d_lon) / d_lon) + 0.5)
    lon_cpr = xz % (2**17)
    return lat_cpr, lon_cpr

def make_pos_me(tc, ss, alt_ft, fflag, lat, lon):
    """Create ME field for airborne position (TC 9-18)."""
    alt_code = encode_altitude(alt_ft)
    lat_cpr, lon_cpr = cpr_encode(lat, lon, fflag)
    me = 0
    me |= (tc & 0x1F) << 51
    me |= (ss & 0x03) << 49
    me |= (alt_code & 0xFFF) << 36
    me |= (fflag & 0x01) << 34
    me |= (lat_cpr & 0x1FFFF) << 17
    me |= (lon_cpr & 0x1FFFF)
    return me.to_bytes(7, 'big')

def vel_components(gs_knots, heading_deg):
    """Convert ground speed and heading to encoded EW/NS components."""
    heading_rad = math.radians(heading_deg)
    vew_actual = gs_knots * math.sin(heading_rad)
    vns_actual = gs_knots * math.cos(heading_rad)
    dew = 0 if vew_actual >= 0 else 1
    dns = 0 if vns_actual >= 0 else 1
    vew_enc = int(round(abs(vew_actual))) + 1
    vns_enc = int(round(abs(vns_actual))) + 1
    return vew_enc, dew, vns_enc, dns

def vr_encode(vr_fpm):
    """Encode vertical rate in ft/min to 9-bit value."""
    svr = 0 if vr_fpm >= 0 else 1
    vr_enc = int(round(abs(vr_fpm) / 64.0)) + 1
    return vr_enc, svr

def make_vel_me(gs_knots, heading_deg, vr_fpm):
    """Create ME field for airborne velocity (TC=19, ST=1)."""
    vew_enc, dew, vns_enc, dns = vel_components(gs_knots, heading_deg)
    vr_enc, svr = vr_encode(vr_fpm)
    me = 0
    me |= (19 & 0x1F) << 51       # TC
    me |= (1 & 0x07) << 48        # ST=1
    me |= (dew & 0x01) << 42      # Dew
    me |= (vew_enc & 0x3FF) << 32 # Vew
    me |= (dns & 0x01) << 31      # Dns
    me |= (vns_enc & 0x3FF) << 21 # Vns
    me |= (svr & 0x01) << 19      # Svr
    me |= (vr_enc & 0x1FF) << 10  # Vr
    return me.to_bytes(7, 'big')

def make_df17(icao, me_bytes):
    """Construct a 14-byte DF17 message with correct CRC-24."""
    data = bytes([0x8D]) + icao.to_bytes(3, 'big') + me_bytes
    crc = crc24(data)
    return data + crc.to_bytes(3, 'big')

def flip_bit(msg_bytes, bit_pos):
    """Flip a single bit in the message (bit_pos 0 = MSB of byte 0)."""
    msg = bytearray(msg_bytes)
    byte_idx = bit_pos // 8
    bit_idx = 7 - (bit_pos % 8)
    msg[byte_idx] ^= (1 << bit_idx)
    return bytes(msg)

# ---- Aircraft definitions ----
aircraft = [
    {
        'icao': 0xA1B2C3, 'callsign': 'UAL1234',
        'lat': 40.6413, 'lon': -73.7781, 'alt': 38000,
        'gs': 450, 'heading': 90, 'vr': 0,
    },
    {
        'icao': 0x3C4586, 'callsign': 'DLH9876',
        'lat': 51.4700, 'lon': -0.4543, 'alt': 35000,
        'gs': 480, 'heading': 270, 'vr': -1024,
    },
    {
        'icao': 0x780ABC, 'callsign': 'ANA567',
        'lat': 35.5494, 'lon': 139.7798, 'alt': 3000,
        'gs': 180, 'heading': 180, 'vr': -1536,
    },
    {
        'icao': 0xC0FFEE, 'callsign': 'TEST42',
        'lat': -33.9461, 'lon': 151.1772, 'alt': 41000,
        'gs': 520, 'heading': 45, 'vr': 0,
    },
    {
        'icao': 0xDEAD01, 'callsign': 'N12345',
        'lat': None, 'lon': None, 'alt': None,
        'gs': None, 'heading': None, 'vr': None,
    },
]

messages = []

for ac in aircraft:
    # Identification message (TC=4)
    me = make_id_me(4, 0, ac['callsign'])
    msg = make_df17(ac['icao'], me)
    messages.append(msg)

    if ac['lat'] is not None:
        # Position even (TC=11)
        me = make_pos_me(11, 0, ac['alt'], 0, ac['lat'], ac['lon'])
        msg = make_df17(ac['icao'], me)
        messages.append(msg)

        # Position odd (TC=11)
        me = make_pos_me(11, 0, ac['alt'], 1, ac['lat'], ac['lon'])
        msg = make_df17(ac['icao'], me)
        messages.append(msg)

        # Velocity (TC=19)
        me = make_vel_me(ac['gs'], ac['heading'], ac['vr'])
        msg = make_df17(ac['icao'], me)
        messages.append(msg)

# Messages layout:
# 0:  AC1 ID      1:  AC1 pos_even   2:  AC1 pos_odd   3:  AC1 vel
# 4:  AC2 ID      5:  AC2 pos_even   6:  AC2 pos_odd   7:  AC2 vel
# 8:  AC3 ID      9:  AC3 pos_even  10:  AC3 pos_odd  11:  AC3 vel
# 12: AC4 ID     13:  AC4 pos_even  14:  AC4 pos_odd  15:  AC4 vel
# 16: AC5 ID

# Introduce single-bit errors
messages[10] = flip_bit(messages[10], 50)  # AC3 pos_odd: bit 50
messages[12] = flip_bit(messages[12], 73)  # AC4 ID: bit 73

# Add an uncorrectable message (multi-bit corruption)
bad = bytearray(make_df17(0x123456, make_id_me(4, 0, 'BADMSG')))
bad[5] ^= 0xFF
bad[8] ^= 0xAA
bad[11] ^= 0x55
messages.append(bytes(bad))

# Write to /app/messages.hex
os.makedirs('/app', exist_ok=True)
with open('/app/messages.hex', 'w') as f:
    for msg in messages:
        f.write(msg.hex().upper() + '\n')

# Verification: decode and print for build-log verification
print(f"Generated {len(messages)} messages")
for i, msg in enumerate(messages):
    c = crc24(msg)
    status = "VALID" if c == 0 else f"CRC={c:06X}"
    print(f"  [{i:2d}] {msg.hex().upper()} {status}")
