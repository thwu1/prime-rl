#!/usr/bin/env python3
"""Generate a synthetic ArduPilot DataFlash binary log for forensic analysis task."""
import struct
import math
import os

HEADER = b'\xa3\x95'

# Message type constants
FMT_TYPE = 128
PARM_TYPE = 129
GPS_TYPE = 130
ATT_TYPE = 131
BARO_TYPE = 132
MODE_TYPE = 133
EKF4_TYPE = 134
VIBE_TYPE = 135
MSG_TYPE = 136

# Format character to struct format and size
FMT_CHAR_SIZE = {
    'b': 1, 'B': 1, 'h': 2, 'H': 2, 'i': 4, 'I': 4,
    'f': 4, 'd': 8, 'n': 4, 'N': 16, 'Z': 64,
    'c': 2, 'C': 2, 'e': 4, 'E': 4, 'L': 4, 'M': 1,
    'q': 8, 'Q': 8,
}


def pad(s, length):
    b = s.encode('ascii') if isinstance(s, str) else s
    return b[:length].ljust(length, b'\x00')


def calc_payload_size(fmt_str):
    return sum(FMT_CHAR_SIZE[c] for c in fmt_str)


def write_msg(f, msg_type, data):
    f.write(HEADER + struct.pack('B', msg_type) + data)


def write_fmt(f, type_id, name, fmt_str, labels):
    payload_size = calc_payload_size(fmt_str)
    total_length = 3 + payload_size  # header(2) + type(1) + payload
    data = struct.pack('BB', type_id, total_length)
    data += pad(name, 4)
    data += pad(fmt_str, 16)
    data += pad(labels, 64)
    write_msg(f, FMT_TYPE, data)


def write_parm(f, time_us, name, value):
    data = struct.pack('<Q', time_us)
    data += pad(name, 16)
    data += struct.pack('<f', value)
    write_msg(f, PARM_TYPE, data)


def write_gps(f, time_us, status, lat, lon, alt, spd, hdop, nsats, vz):
    data = struct.pack('<QBfffffBf', time_us, status, lat, lon, alt, spd, hdop, nsats, vz)
    write_msg(f, GPS_TYPE, data)


def write_att(f, time_us, roll, pitch, yaw):
    data = struct.pack('<Qfff', time_us, roll, pitch, yaw)
    write_msg(f, ATT_TYPE, data)


def write_baro(f, time_us, alt, press, temp):
    data = struct.pack('<Qfff', time_us, alt, press, temp)
    write_msg(f, BARO_TYPE, data)


def write_mode(f, time_us, mode, reason):
    data = struct.pack('<QBB', time_us, mode, reason)
    write_msg(f, MODE_TYPE, data)


def write_ekf4(f, time_us, variance, offset, flags):
    data = struct.pack('<QffH', time_us, variance, offset, flags)
    write_msg(f, EKF4_TYPE, data)


def write_vibe(f, time_us, vibe_x, vibe_y, vibe_z, clip):
    data = struct.pack('<QfffI', time_us, vibe_x, vibe_y, vibe_z, clip)
    write_msg(f, VIBE_TYPE, data)


def write_message(f, time_us, message):
    data = struct.pack('<Q', time_us)
    data += pad(message, 64)
    write_msg(f, MSG_TYPE, data)


def main():
    os.makedirs('/app', exist_ok=True)

    with open('/app/flight.bin', 'wb') as f:
        # === FMT DEFINITIONS ===
        # FMT for FMT itself
        fmt_payload = calc_payload_size('BBnNZ')  # 86
        fmt_total = 3 + fmt_payload  # 89
        write_fmt(f, FMT_TYPE, 'FMT', 'BBnNZ', 'Type,Length,Name,Format,Labels')

        # Data message formats
        write_fmt(f, PARM_TYPE, 'PARM', 'QNf', 'TimeUS,Name,Value')
        write_fmt(f, GPS_TYPE, 'GPS', 'QBfffffBf', 'TimeUS,Status,Lat,Lon,Alt,Spd,HDop,NSats,VZ')
        write_fmt(f, ATT_TYPE, 'ATT', 'Qfff', 'TimeUS,Roll,Pitch,Yaw')
        write_fmt(f, BARO_TYPE, 'BARO', 'Qfff', 'TimeUS,Alt,Press,Temp')
        write_fmt(f, MODE_TYPE, 'MODE', 'QBB', 'TimeUS,Mode,Reason')
        write_fmt(f, EKF4_TYPE, 'EKF4', 'QffH', 'TimeUS,Variance,Offset,Flags')
        write_fmt(f, VIBE_TYPE, 'VIBE', 'QfffI', 'TimeUS,VibeX,VibeY,VibeZ,Clip')
        write_fmt(f, MSG_TYPE, 'MSG', 'QZ', 'TimeUS,Message')

        # === PARAMETER MESSAGES (15 total) ===
        t_base = 1_000_000
        params = [
            ('FS_EKF_THRESH', 0.8),       # valid (range 0.1-1.0)
            ('FS_EKF_ACTION', 1.0),        # valid (range 0-3)
            ('FS_THR_ENABLE', 1.0),        # valid (range 0-7)
            ('FS_GCS_ENABLE', 1.0),        # valid (range 0-7)
            ('FS_BATT_ENABLE', 3.0),       # MISCONFIGURED: max is 2
            ('EK3_GPS_CHECK', 31.0),       # valid (range 0-255)
            ('EK3_CHECK_SCALE', 100.0),    # valid initially
            ('PILOT_THR_FILT', 15.0),      # MISCONFIGURED: max is 10
            ('ARMING_CHECK', 1.0),         # valid
            ('GPS_TYPE', 1.0),             # valid
            ('INS_LOG_BAT_OPT', 4.0),     # valid
            ('FRAME_TYPE', 1.0),           # valid
            ('RTL_ALT', 1500.0),           # valid
            ('WPNAV_SPEED', 500.0),        # valid
            ('EK3_CHECK_SCALE', 50.0),     # MISCONFIGURED: overrides to below min 100
        ]
        for i, (name, value) in enumerate(params):
            write_parm(f, t_base + i * 100_000, name, value)

        # === MODE MESSAGES (4 total) ===
        write_mode(f, 5_000_000, 0, 0)      # STABILIZE at t=5s
        write_mode(f, 15_000_000, 2, 1)     # ALT_HOLD at t=15s
        write_mode(f, 30_000_000, 3, 1)     # AUTO at t=30s
        write_mode(f, 142_000_000, 9, 4)    # LAND at t=142s (failsafe)

        # === MSG MESSAGES (4 total) ===
        write_message(f, 5_000_000, 'ArduCopter V4.5.1')
        write_message(f, 14_000_000, 'Arming motors')
        write_message(f, 142_000_000, 'EKF variance')
        write_message(f, 142_500_000, 'EKF failsafe - Loss of navigation')

        # === SENSOR DATA (1Hz from t=5s to t=180s, 176 messages per type) ===
        for t_sec in range(5, 181):
            t_us = t_sec * 1_000_000

            # --- GPS ---
            if t_sec < 120:
                gps_status = 3
                lat = -35.3633 + 0.0001 * math.sin(t_sec * 0.05)
                lon = 149.1652 + 0.0001 * math.cos(t_sec * 0.05)
                hdop = 1.2
                nsats = 12
            elif t_sec < 145:
                gps_status = 1  # degraded
                lat = -35.3633 + 0.005 * math.sin(t_sec * 2.0)
                lon = 149.1652 + 0.005 * math.cos(t_sec * 2.0)
                hdop = 8.5
                nsats = 3
            else:
                gps_status = 2  # recovering
                lat = -35.3633
                lon = 149.1652
                hdop = 3.5
                nsats = 7

            # Altitude profile
            if t_sec < 15:
                alt = 0.0
            elif t_sec <= 50:
                alt = float(t_sec - 15)  # climb 1 m/s
            elif t_sec < 120:
                alt = 35.0
            elif t_sec < 145:
                alt = 35.0 - (t_sec - 120) * 0.2
            else:
                alt = max(0.0, 30.0 - float(t_sec - 145))

            spd = 5.0 if 30 <= t_sec < 145 else 0.5
            vz = -1.0 if t_sec >= 145 else 0.0

            write_gps(f, t_us, gps_status, lat, lon, alt, spd, hdop, nsats, vz)

            # --- ATT ---
            roll = 2.0 * math.sin(t_sec * 0.2)
            pitch = 3.0 * math.cos(t_sec * 0.15)
            yaw = float((t_sec * 2) % 360)
            write_att(f, t_us, roll, pitch, yaw)

            # --- BARO ---
            baro_alt = alt  # clean altitude, no noise
            press = 101325.0 - baro_alt * 12.0
            temp = 25.0
            write_baro(f, t_us, baro_alt, press, temp)

            # --- EKF4 ---
            if t_sec < 120:
                variance = 0.2
            elif t_sec <= 145:
                variance = 0.2 + (t_sec - 120) * 0.04
            else:
                variance = 1.2 - (t_sec - 145) * 0.02

            offset = 0.1 * math.sin(t_sec * 0.2)
            flags = 0 if variance <= 0.8 else 1
            write_ekf4(f, t_us, variance, offset, flags)

            # --- VIBE ---
            if t_sec < 155:
                vibe_base = 5.0
            elif t_sec <= 170:
                vibe_base = 5.0 + (t_sec - 155) * 3.0
            else:
                vibe_base = 50.0

            vibe_x = vibe_base * 0.3
            vibe_y = vibe_base * 0.4
            vibe_z = vibe_base
            clip = 0 if vibe_base < 30 else int(vibe_base - 29)
            write_vibe(f, t_us, vibe_x, vibe_y, vibe_z, clip)

    file_size = os.path.getsize('/app/flight.bin')
    print(f"Generated /app/flight.bin ({file_size} bytes)")


if __name__ == '__main__':
    main()
