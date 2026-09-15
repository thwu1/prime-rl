#!/usr/bin/env python3
"""
Generate multi-station ADS-B message captures for the track fusion task.
Creates /app/stations/{alpha,bravo,charlie}.hex with encoded DF17 messages
including valid messages, single-bit errors, and uncorrectable messages.
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
    return (upper << 5) | (1 << 4) | lower


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


def make_vel_me(gs_knots, heading_deg, vr_fpm):
    """Create ME field for airborne velocity (TC=19, ST=1)."""
    heading_rad = math.radians(heading_deg)
    vew_actual = gs_knots * math.sin(heading_rad)
    vns_actual = gs_knots * math.cos(heading_rad)
    dew = 0 if vew_actual >= 0 else 1
    dns = 0 if vns_actual >= 0 else 1
    vew_enc = int(round(abs(vew_actual))) + 1
    vns_enc = int(round(abs(vns_actual))) + 1
    svr = 0 if vr_fpm >= 0 else 1
    vr_enc = int(round(abs(vr_fpm) / 64.0)) + 1
    me = 0
    me |= (19 & 0x1F) << 51
    me |= (1 & 0x07) << 48
    me |= (dew & 0x01) << 42
    me |= (vew_enc & 0x3FF) << 32
    me |= (dns & 0x01) << 31
    me |= (vns_enc & 0x3FF) << 21
    me |= (svr & 0x01) << 19
    me |= (vr_enc & 0x1FF) << 10
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


def write_station(filepath, messages):
    """Write hex-encoded messages to a station file."""
    with open(filepath, 'w') as f:
        for msg in messages:
            f.write(msg.hex().upper() + '\n')


# ========== Build all messages ==========

# Aircraft 1: A1B2C3 / UAL1234 — FL380, heading 90, 450kts
a1b2c3_id = make_df17(0xA1B2C3, make_id_me(4, 0, 'UAL1234'))
a1b2c3_pos_even = make_df17(0xA1B2C3, make_pos_me(11, 0, 38000, 0, 40.6413, -73.7781))
a1b2c3_pos_odd = make_df17(0xA1B2C3, make_pos_me(11, 0, 38000, 1, 40.6413, -73.7781))
a1b2c3_vel = make_df17(0xA1B2C3, make_vel_me(450, 90, 0))

# Aircraft 2: 3C4586 / DLH9876 — FL350, heading 270, 480kts, descending
dlh_id = make_df17(0x3C4586, make_id_me(4, 0, 'DLH9876'))
dlh_pos_even = make_df17(0x3C4586, make_pos_me(11, 0, 35000, 0, 51.4700, -0.4543))
dlh_pos_odd = make_df17(0x3C4586, make_pos_me(11, 0, 35000, 1, 51.4700, -0.4543))
dlh_vel = make_df17(0x3C4586, make_vel_me(480, 270, -1024))

# Aircraft 3: 780ABC / ANA567 — 3000ft, heading 180, 180kts, descending
ana_id = make_df17(0x780ABC, make_id_me(4, 0, 'ANA567'))
ana_pos_even = make_df17(0x780ABC, make_pos_me(11, 0, 3000, 0, 35.5494, 139.7798))
ana_pos_odd = make_df17(0x780ABC, make_pos_me(11, 0, 3000, 1, 35.5494, 139.7798))
ana_vel = make_df17(0x780ABC, make_vel_me(180, 180, -1536))

# Aircraft 4: C0FFEE / SWA789 — FL280, heading 135, 400kts, climbing
swa_id = make_df17(0xC0FFEE, make_id_me(4, 0, 'SWA789'))
swa_pos_even = make_df17(0xC0FFEE, make_pos_me(11, 0, 28000, 0, -33.9461, 151.1772))
swa_pos_odd = make_df17(0xC0FFEE, make_pos_me(11, 0, 28000, 1, -33.9461, 151.1772))
swa_vel = make_df17(0xC0FFEE, make_vel_me(400, 135, 512))

# Aircraft 5: BEEF42 / SPOOF1 — THE SPOOF: two positions ~900nm apart
spoof_id = make_df17(0xBEEF42, make_id_me(4, 0, 'SPOOF1'))
spoof_pos_even_1 = make_df17(0xBEEF42, make_pos_me(11, 0, 32000, 0, 40.0, -74.0))
spoof_pos_odd_1 = make_df17(0xBEEF42, make_pos_me(11, 0, 32000, 1, 40.0, -74.0))
spoof_pos_even_2 = make_df17(0xBEEF42, make_pos_me(11, 0, 32000, 0, 55.0, -74.0))
spoof_pos_odd_2 = make_df17(0xBEEF42, make_pos_me(11, 0, 32000, 1, 55.0, -74.0))
spoof_vel = make_df17(0xBEEF42, make_vel_me(200, 0, 0))

# Aircraft 6: DEAD01 / N12345 — identification only, no position/velocity
dead_id = make_df17(0xDEAD01, make_id_me(4, 0, 'N12345'))

# ========== Introduce single-bit errors ==========
a1b2c3_pos_even_err = flip_bit(a1b2c3_pos_even, 45)  # bravo receives corrupted
dlh_vel_err = flip_bit(dlh_vel, 30)                    # alpha receives corrupted
ana_pos_odd_err = flip_bit(ana_pos_odd, 60)             # bravo receives corrupted

# ========== Uncorrectable garbage messages ==========
bad_bravo = bytearray(make_df17(0x123456, make_id_me(4, 0, 'BADMSG')))
bad_bravo[5] ^= 0xFF
bad_bravo[8] ^= 0xAA
bad_bravo[11] ^= 0x55
bad_bravo = bytes(bad_bravo)

bad_charlie = bytearray(make_df17(0x654321, make_id_me(4, 0, 'BADBAD')))
bad_charlie[4] ^= 0xCC
bad_charlie[7] ^= 0x33
bad_charlie[10] ^= 0x77
bad_charlie = bytes(bad_charlie)

# ========== Build station message lists ==========

# Station Alpha: high-altitude receiver (12 messages)
alpha_msgs = [
    a1b2c3_id,             # shared with bravo
    a1b2c3_pos_even,       # clean version (alpha only)
    a1b2c3_pos_odd,        # shared with bravo
    a1b2c3_vel,            # alpha only
    dlh_id,                # shared with bravo
    dlh_vel_err,           # corrupted velocity (alpha only)
    spoof_id,              # shared with bravo
    spoof_pos_even_1,      # alpha only — spoof position 1
    spoof_pos_odd_1,       # alpha only — spoof position 1
    spoof_pos_even_2,      # alpha only — spoof position 2 (jump!)
    spoof_pos_odd_2,       # alpha only — spoof position 2 (jump!)
    spoof_vel,             # alpha only
]

# Station Bravo: wide-area receiver (14 messages)
bravo_msgs = [
    a1b2c3_id,             # duplicate of alpha
    a1b2c3_pos_even_err,   # corrupted version of pos_even
    a1b2c3_pos_odd,        # duplicate of alpha
    dlh_id,                # duplicate of alpha
    dlh_pos_even,          # shared with charlie
    dlh_pos_odd,           # shared with charlie
    dlh_vel,               # shared with charlie (clean version)
    ana_id,                # shared with charlie
    ana_pos_even,          # shared with charlie
    ana_pos_odd_err,       # corrupted (bravo only)
    ana_vel,               # shared with charlie
    dead_id,               # bravo only
    spoof_id,              # duplicate of alpha
    bad_bravo,             # uncorrectable
]

# Station Charlie: approach monitor (12 messages)
charlie_msgs = [
    dlh_pos_even,          # duplicate of bravo
    dlh_pos_odd,           # duplicate of bravo
    dlh_vel,               # duplicate of bravo
    ana_id,                # duplicate of bravo
    ana_pos_even,          # duplicate of bravo
    ana_pos_odd,           # clean version (charlie has it clean!)
    ana_vel,               # duplicate of bravo
    swa_id,                # charlie only
    swa_pos_even,          # charlie only
    swa_pos_odd,           # charlie only
    swa_vel,               # charlie only
    bad_charlie,           # uncorrectable
]

# ========== Write station files ==========
os.makedirs('/app/stations', exist_ok=True)

write_station('/app/stations/alpha.hex', alpha_msgs)
write_station('/app/stations/bravo.hex', bravo_msgs)
write_station('/app/stations/charlie.hex', charlie_msgs)

# ========== Build verification output ==========
total = len(alpha_msgs) + len(bravo_msgs) + len(charlie_msgs)
print(f"Generated station captures: alpha={len(alpha_msgs)}, "
      f"bravo={len(bravo_msgs)}, charlie={len(charlie_msgs)}, total={total}")

for name, msgs in [('alpha', alpha_msgs), ('bravo', bravo_msgs), ('charlie', charlie_msgs)]:
    print(f"\n=== Station {name} ({len(msgs)} messages) ===")
    for i, msg in enumerate(msgs):
        c = crc24(msg)
        status = "VALID" if c == 0 else f"CRC={c:06X}"
        df = (msg[0] >> 3) & 0x1F
        if df == 17:
            icao = f"{msg[1]:02X}{msg[2]:02X}{msg[3]:02X}"
            tc = (msg[4] >> 3) & 0x1F
            print(f"  [{i:2d}] DF{df} ICAO={icao} TC={tc:2d} {status}")
        else:
            print(f"  [{i:2d}] DF{df} {status}")

# Count unique hex strings
all_hex = set()
for msgs in [alpha_msgs, bravo_msgs, charlie_msgs]:
    for msg in msgs:
        all_hex.add(msg.hex().upper())
print(f"\nUnique hex strings: {len(all_hex)}")
print(f"Correctable messages: 3 (a1b2c3_pos_even@45, dlh_vel@30, ana_pos_odd@60)")
print(f"Uncorrectable messages: 2 (bravo garbage, charlie garbage)")
