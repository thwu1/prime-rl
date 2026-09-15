#!/usr/bin/env python3
"""Generate three synthetic ArduPilot DataFlash binary logs for fleet safety assessment."""
import struct
import math
import os

HEADER = b'\xa3\x95'

FMT_TYPE = 128
PARM_TYPE = 129
GPS_TYPE = 130
ATT_TYPE = 131
BARO_TYPE = 132
MODE_TYPE = 133
EKF4_TYPE = 134
VIBE_TYPE = 135
MSG_TYPE = 136

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
    total_length = 3 + payload_size
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


def write_fmt_definitions(f):
    write_fmt(f, FMT_TYPE, 'FMT', 'BBnNZ', 'Type,Length,Name,Format,Labels')
    write_fmt(f, PARM_TYPE, 'PARM', 'QNf', 'TimeUS,Name,Value')
    write_fmt(f, GPS_TYPE, 'GPS', 'QBfffffBf',
              'TimeUS,Status,Lat,Lon,Alt,Spd,HDop,NSats,VZ')
    write_fmt(f, ATT_TYPE, 'ATT', 'Qfff', 'TimeUS,Roll,Pitch,Yaw')
    write_fmt(f, BARO_TYPE, 'BARO', 'Qfff', 'TimeUS,Alt,Press,Temp')
    write_fmt(f, MODE_TYPE, 'MODE', 'QBB', 'TimeUS,Mode,Reason')
    write_fmt(f, EKF4_TYPE, 'EKF4', 'QffH', 'TimeUS,Variance,Offset,Flags')
    write_fmt(f, VIBE_TYPE, 'VIBE', 'QfffI', 'TimeUS,VibeX,VibeY,VibeZ,Clip')
    write_fmt(f, MSG_TYPE, 'MSG', 'QZ', 'TimeUS,Message')


def generate_alpha(filepath):
    """Flight Alpha: Training flight with mild GPS degradation.
    t=10..109 (100 sensor samples), 15 PARMs, 4 MODEs, 3 MSGs.
    Total non-FMT = 500 + 15 + 4 + 3 = 522
    """
    with open(filepath, 'wb') as f:
        write_fmt_definitions(f)

        t_base = 5_000_000
        params = [
            ('FS_EKF_THRESH', 0.8),
            ('FS_EKF_ACTION', 1.0),
            ('FS_THR_ENABLE', 1.0),
            ('FS_GCS_ENABLE', 1.0),
            ('FS_BATT_ENABLE', 0.0),
            ('EK3_GPS_CHECK', 31.0),
            ('EK3_CHECK_SCALE', 100.0),
            ('PILOT_THR_FILT', 5.0),
            ('ARMING_CHECK', 1.0),
            ('GPS_TYPE', 1.0),
            ('INS_LOG_BAT_OPT', 4.0),
            ('FRAME_TYPE', 1.0),
            ('RTL_ALT', 1500.0),
            ('WPNAV_SPEED', 500.0),
            ('INS_ACCEL_FILTER', 15.0),
        ]
        for i, (name, value) in enumerate(params):
            write_parm(f, t_base + i * 100_000, name, value)

        write_mode(f, 10_000_000, 0, 0)
        write_mode(f, 20_000_000, 2, 1)
        write_mode(f, 50_000_000, 3, 1)
        write_mode(f, 100_000_000, 6, 1)

        write_message(f, 10_000_000, 'ArduCopter V4.5.1')
        write_message(f, 19_000_000, 'Arming motors')
        write_message(f, 100_000_000, 'Reached Home')

        for t_sec in range(10, 110):
            t_us = t_sec * 1_000_000

            if t_sec < 80 or t_sec >= 90:
                gps_status = 3
            else:
                gps_status = 2

            lat = -35.3633 + 0.0001 * math.sin(t_sec * 0.05)
            lon = 149.1652 + 0.0001 * math.cos(t_sec * 0.05)

            if t_sec < 20:
                alt = 0.0
            elif t_sec <= 50:
                alt = float(t_sec - 20)
            elif t_sec < 100:
                alt = 30.0
            else:
                alt = max(0.0, 30.0 - (t_sec - 100) * 3.0)

            hdop = 1.2 if gps_status == 3 else 4.0
            nsats = 12 if gps_status == 3 else 6
            spd = 5.0 if 50 <= t_sec < 100 else 0.5
            vz = 0.0
            write_gps(f, t_us, gps_status, lat, lon, alt, spd, hdop, nsats, vz)

            roll = 2.0 * math.sin(t_sec * 0.2)
            pitch = 3.0 * math.cos(t_sec * 0.15)
            yaw = float((t_sec * 2) % 360)
            write_att(f, t_us, roll, pitch, yaw)

            baro_alt = alt
            press = 101325.0 - baro_alt * 12.0
            write_baro(f, t_us, baro_alt, press, 25.0)

            if t_sec < 80:
                variance = 0.2
            elif t_sec <= 89:
                variance = 0.2 + (t_sec - 80) / 9.0 * 0.3
            else:
                variance = 0.2
            offset = 0.1 * math.sin(t_sec * 0.2)
            write_ekf4(f, t_us, variance, offset, 0)

            vibe_z = 20.0
            write_vibe(f, t_us, vibe_z * 0.3, vibe_z * 0.4, vibe_z, 0)

    print(f"Generated {filepath} ({os.path.getsize(filepath)} bytes)")


def generate_bravo(filepath):
    """Flight Bravo: Survey mission with vibration-induced EKF issues.
    t=10..129 (120 sensor samples), 15 PARMs, 4 MODEs, 3 MSGs.
    Total non-FMT = 600 + 15 + 4 + 3 = 622
    """
    with open(filepath, 'wb') as f:
        write_fmt_definitions(f)

        t_base = 5_000_000
        params = [
            ('FS_EKF_THRESH', 0.8),
            ('FS_EKF_ACTION', 1.0),
            ('FS_THR_ENABLE', 1.0),
            ('FS_GCS_ENABLE', 1.0),
            ('FS_BATT_ENABLE', 0.0),
            ('EK3_GPS_CHECK', 31.0),
            ('EK3_CHECK_SCALE', 100.0),
            ('PILOT_THR_FILT', 15.0),
            ('ARMING_CHECK', 1.0),
            ('GPS_TYPE', 1.0),
            ('INS_LOG_BAT_OPT', 4.0),
            ('FRAME_TYPE', 1.0),
            ('RTL_ALT', 1500.0),
            ('WPNAV_SPEED', 500.0),
            ('INS_ACCEL_FILTER', 15.0),
        ]
        for i, (name, value) in enumerate(params):
            write_parm(f, t_base + i * 100_000, name, value)

        write_mode(f, 10_000_000, 0, 0)
        write_mode(f, 20_000_000, 2, 1)
        write_mode(f, 40_000_000, 3, 1)
        write_mode(f, 110_000_000, 9, 4)

        write_message(f, 10_000_000, 'ArduCopter V4.5.1')
        write_message(f, 19_000_000, 'Arming motors')
        write_message(f, 110_000_000, 'EKF variance')

        for t_sec in range(10, 130):
            t_us = t_sec * 1_000_000

            gps_status = 3
            lat = -35.3633 + 0.0002 * math.sin(t_sec * 0.03)
            lon = 149.1652 + 0.0002 * math.cos(t_sec * 0.03)

            if t_sec < 20:
                alt = 0.0
            elif t_sec <= 60:
                alt = float(t_sec - 20)
            elif t_sec < 110:
                alt = 40.0
            else:
                alt = max(0.0, 40.0 - (t_sec - 110) * 2.0)

            hdop = 1.0
            nsats = 14
            spd = 5.0 if 40 <= t_sec < 110 else 0.5
            vz = -2.0 if t_sec >= 110 else 0.0
            write_gps(f, t_us, gps_status, lat, lon, alt, spd, hdop, nsats, vz)

            roll = 1.5 * math.sin(t_sec * 0.25)
            pitch = 2.0 * math.cos(t_sec * 0.2)
            yaw = float((t_sec * 3) % 360)
            write_att(f, t_us, roll, pitch, yaw)

            baro_alt = alt
            press = 101325.0 - baro_alt * 12.0
            write_baro(f, t_us, baro_alt, press, 24.0)

            if t_sec < 100:
                variance = 0.2
            elif t_sec <= 120:
                variance = 0.2 + (t_sec - 100) / 20.0 * 0.75
            else:
                variance = 0.95 - (t_sec - 120) / 10.0 * 0.35
            offset = 0.05 * math.sin(t_sec * 0.15)
            flags = 0 if variance <= 0.8 else 1
            write_ekf4(f, t_us, variance, offset, flags)

            if t_sec < 80:
                vibe_z = 8.0
            elif t_sec <= 109:
                vibe_z = 8.0 + (t_sec - 80) * 37.0 / 29.0
            else:
                vibe_z = 35.0
            vibe_x = vibe_z * 0.3
            vibe_y = vibe_z * 0.4
            clip = 0 if vibe_z < 30 else int(vibe_z - 29)
            write_vibe(f, t_us, vibe_x, vibe_y, vibe_z, clip)

    print(f"Generated {filepath} ({os.path.getsize(filepath)} bytes)")


def generate_charlie(filepath):
    """Flight Charlie: Autonomous mission with compound GPS/EKF/vibration cascade.
    t=5..180 (176 sensor samples), 16 PARMs (incl override), 4 MODEs, 4 MSGs.
    Total non-FMT = 880 + 16 + 4 + 4 = 904
    """
    with open(filepath, 'wb') as f:
        write_fmt_definitions(f)

        t_base = 1_000_000
        params = [
            ('FS_EKF_THRESH', 0.8),
            ('FS_EKF_ACTION', 1.0),
            ('FS_THR_ENABLE', 1.0),
            ('FS_GCS_ENABLE', 1.0),
            ('FS_BATT_ENABLE', 3.0),
            ('EK3_GPS_CHECK', 31.0),
            ('EK3_CHECK_SCALE', 100.0),
            ('PILOT_THR_FILT', 15.0),
            ('ARMING_CHECK', 1.0),
            ('GPS_TYPE', 1.0),
            ('INS_LOG_BAT_OPT', 4.0),
            ('FRAME_TYPE', 1.0),
            ('RTL_ALT', 1500.0),
            ('WPNAV_SPEED', 500.0),
            ('EK3_CHECK_SCALE', 50.0),
            ('INS_ACCEL_FILTER', 15.0),
        ]
        for i, (name, value) in enumerate(params):
            write_parm(f, t_base + i * 100_000, name, value)

        write_mode(f, 5_000_000, 0, 0)
        write_mode(f, 15_000_000, 2, 1)
        write_mode(f, 30_000_000, 3, 1)
        write_mode(f, 142_000_000, 9, 4)

        write_message(f, 5_000_000, 'ArduCopter V4.5.1')
        write_message(f, 14_000_000, 'Arming motors')
        write_message(f, 142_000_000, 'EKF variance')
        write_message(f, 142_500_000, 'EKF failsafe - Loss of navigation')

        for t_sec in range(5, 181):
            t_us = t_sec * 1_000_000

            if t_sec < 120:
                gps_status = 3
                lat = -35.3633 + 0.0001 * math.sin(t_sec * 0.05)
                lon = 149.1652 + 0.0001 * math.cos(t_sec * 0.05)
                hdop = 1.2
                nsats = 12
            elif t_sec < 145:
                gps_status = 1
                lat = -35.3633 + 0.005 * math.sin(t_sec * 2.0)
                lon = 149.1652 + 0.005 * math.cos(t_sec * 2.0)
                hdop = 8.5
                nsats = 3
            else:
                gps_status = 2
                lat = -35.3633
                lon = 149.1652
                hdop = 3.5
                nsats = 7

            if t_sec < 15:
                alt = 0.0
            elif t_sec <= 50:
                alt = float(t_sec - 15)
            elif t_sec < 120:
                alt = 35.0
            elif t_sec < 145:
                alt = 35.0 - (t_sec - 120) * 0.2
            else:
                alt = max(0.0, 30.0 - float(t_sec - 145))

            spd = 5.0 if 30 <= t_sec < 145 else 0.5
            vz = -1.0 if t_sec >= 145 else 0.0
            write_gps(f, t_us, gps_status, lat, lon, alt, spd, hdop, nsats, vz)

            roll = 2.0 * math.sin(t_sec * 0.2)
            pitch = 3.0 * math.cos(t_sec * 0.15)
            yaw = float((t_sec * 2) % 360)
            write_att(f, t_us, roll, pitch, yaw)

            baro_alt = alt
            press = 101325.0 - baro_alt * 12.0
            write_baro(f, t_us, baro_alt, press, 25.0)

            if t_sec < 120:
                variance = 0.2
            elif t_sec <= 145:
                variance = 0.2 + (t_sec - 120) * 0.04
            else:
                variance = 1.2 - (t_sec - 145) * 0.02
            offset = 0.1 * math.sin(t_sec * 0.2)
            flags = 0 if variance <= 0.8 else 1
            write_ekf4(f, t_us, variance, offset, flags)

            if t_sec < 155:
                vibe_z = 5.0
            elif t_sec <= 170:
                vibe_z = 5.0 + (t_sec - 155) * 3.0
            else:
                vibe_z = 50.0
            vibe_x = vibe_z * 0.3
            vibe_y = vibe_z * 0.4
            clip = 0 if vibe_z < 30 else int(vibe_z - 29)
            write_vibe(f, t_us, vibe_x, vibe_y, vibe_z, clip)

    print(f"Generated {filepath} ({os.path.getsize(filepath)} bytes)")


def main():
    os.makedirs('/app/flights', exist_ok=True)
    generate_alpha('/app/flights/flight_alpha.bin')
    generate_bravo('/app/flights/flight_bravo.bin')
    generate_charlie('/app/flights/flight_charlie.bin')


if __name__ == '__main__':
    main()
