#!/usr/bin/env python3
"""Generate a binary DataFlash flight log for the multi-core EKF forensics task.

Creates a valid ArduPilot-format .bin file with interleaved EKF innovation
data from two filter cores, GPS status, altitude telemetry, core-switch
events, and parameter records. The binary format is compatible with
pymavlink's DFReader_binary.
"""

import struct
import random
import math
import os

random.seed(42)

# ── Flight configuration ──
N = 2000
DT_US = 20000       # 50 Hz
START_US = 1000000

# Flight phases (sample indices)
GROUND1_END = 150
TAKEOFF_END = 300
CRUISE_END = 1700
LANDING_END = 1850

# Primary core: core 0 for samples 0..1199, core 1 for 1200..1999
LANE_SWITCH_SAMPLE = 1200

# GPS outage
GPS_OUTAGE_START = 600
GPS_OUTAGE_END = 1000

# Mag bias on core 0 only
MAG_BIAS_START = 1000
MAG_BIAS_END = 1400
MAG_BIAS_VALUE = 0.20

# Channel defs: (label, truth_noise, config_noise, process_std)
CHANNELS_VP = [
    ('IVN',  0.80, 0.30, 0.15),
    ('IVE',  0.80, 0.30, 0.15),
    ('IVD',  0.50, 0.50, 0.10),
    ('IPN',  1.50, 0.50, 0.30),
    ('IPE',  1.50, 0.50, 0.30),
    ('IAlt', 3.00, 1.00, 0.50),
]

CHANNELS_MY = [
    ('IMX',  0.05, 0.05, 0.01),
    ('IMY',  0.05, 0.05, 0.01),
    ('IMZ',  0.05, 0.05, 0.01),
    ('IYaw', 0.50, 0.50, 0.05),
]

GPS_FIELDS = {'IVN', 'IVE', 'IVD', 'IPN', 'IPE'}

# Ground-phase biases (simulate pre-flight EKF convergence artifacts)
GROUND_BIASES = {
    'IVN': 3.0, 'IVE': -2.5, 'IVD': 1.5,
    'IPN': 5.0, 'IPE': -4.0, 'IAlt': 8.0,
    'IMX': 0.15, 'IMY': -0.12, 'IMZ': 0.18,
    'IYaw': 1.2,
}

# Parameters recorded at start of flight
PARAMS = [
    ('EK3_VELNE_NOISE', 0.3),
    ('EK3_VELD_NOISE',  0.5),
    ('EK3_POSNE_NOISE', 0.5),
    ('EK3_ALT_NOISE',   1.0),
    ('EK3_MAG_NOISE',   0.05),
    ('EK3_YAW_NOISE',   0.5),
    ('EK3_VEL_GATE',    500),
    ('EK3_POS_GATE',    500),
    ('EK3_HGT_GATE',    500),
    ('EK3_MAG_GATE',    300),
    ('EK3_YAW_GATE',    300),
    ('EK3_IMU_MASK',    3),
]

# ── Binary DataFlash constants ──
HEAD1 = 0xA3
HEAD2 = 0x95
FMT_TYPE = 128

FCHAR = {
    'B': ('B', 1), 'H': ('H', 2), 'I': ('I', 4),
    'f': ('f', 4), 'Q': ('Q', 8),
    'n': ('4s', 4), 'N': ('16s', 16), 'Z': ('64s', 64),
    'b': ('b', 1), 'h': ('h', 2), 'i': ('i', 4), 'q': ('q', 8),
}

# (type_id, name, format, labels)
MSG_DEFS = [
    (1,  'PARM', 'QNf',       'TimeUS,Name,Value'),
    (2,  'GPS',  'QBBIHBf',   'TimeUS,I,Status,GMS,GWk,NSats,HDop'),
    (3,  'XKF1', 'QBffffff',  'TimeUS,C,IVN,IVE,IVD,IPN,IPE,IAlt'),
    (4,  'XKF2', 'QBffff',    'TimeUS,C,IMX,IMY,IMZ,IYaw'),
    (5,  'XKF4', 'QBffffff',  'TimeUS,C,SVN,SVE,SVD,SPN,SPE,SAlt'),
    (6,  'XKF5', 'QBffff',    'TimeUS,C,SMX,SMY,SMZ,SYaw'),
    (7,  'CTUN', 'Qff',       'TimeUS,Alt,DAlt'),
    (8,  'STAT', 'QBB',       'TimeUS,MainCoreId,Flags'),
    (9,  'MSG',  'QZ',        'TimeUS,Message'),
]


def payload_size(fmt):
    return sum(FCHAR[c][1] for c in fmt)


def struct_fmt(fmt):
    return '<' + ''.join(FCHAR[c][0] for c in fmt)


def write_fmt(f, type_id, name, fmt_str, labels):
    """Write a FMT definition message."""
    psize = payload_size(fmt_str)
    msg_len = 3 + psize
    f.write(struct.pack('<BBB', HEAD1, HEAD2, FMT_TYPE))
    f.write(struct.pack('<BB', type_id, msg_len))
    f.write(name.encode('ascii').ljust(4, b'\x00')[:4])
    f.write(fmt_str.encode('ascii').ljust(16, b'\x00')[:16])
    f.write(labels.encode('ascii').ljust(64, b'\x00')[:64])


def write_msg(f, type_id, fmt_str, values):
    """Write a data message."""
    sfmt = struct_fmt(fmt_str)
    packed = []
    for i, c in enumerate(fmt_str):
        v = values[i]
        if c in ('n', 'N', 'Z'):
            sz = FCHAR[c][1]
            if isinstance(v, str):
                v = v.encode('ascii')
            v = v.ljust(sz, b'\x00')[:sz]
        packed.append(v)
    f.write(struct.pack('<BBB', HEAD1, HEAD2, type_id))
    f.write(struct.pack(sfmt, *packed))


def is_cruise(i):
    return TAKEOFF_END <= i < CRUISE_END


def is_ground(i):
    return i < GROUND1_END or i >= LANDING_END


def is_transition(i):
    """Takeoff or landing phase."""
    return (GROUND1_END <= i < TAKEOFF_END) or (CRUISE_END <= i < LANDING_END)


def ground_bias(field, i):
    """Bias added only during ground phases (not takeoff/landing)."""
    if is_ground(i):
        return GROUND_BIASES.get(field, 0.0)
    return 0.0


def noise_scale(i):
    """Innovation std multiplier. Higher during transitions."""
    if is_transition(i):
        return 3.0
    return 1.0


def altitude(i):
    if i < GROUND1_END:
        return 0.0
    elif i < TAKEOFF_END:
        frac = (i - GROUND1_END) / (TAKEOFF_END - GROUND1_END)
        return 50.0 * frac
    elif i < CRUISE_END:
        return 50.0 + random.gauss(0, 0.3)
    elif i < LANDING_END:
        frac = (i - CRUISE_END) / (LANDING_END - CRUISE_END)
        return 50.0 * (1.0 - frac)
    else:
        return 0.0


def main():
    os.makedirs('/app/flight_log', exist_ok=True)

    with open('/app/flight_log/flight.bin', 'wb') as f:
        # FMT for FMT
        write_fmt(f, FMT_TYPE, 'FMT', 'BBnNZ',
                  'Type,Length,Name,Format,Columns')

        # FMT for each message type
        for tid, name, fmt_str, labels in MSG_DEFS:
            write_fmt(f, tid, name, fmt_str, labels)

        # PARM messages (at t=0)
        t = START_US
        for pname, pval in PARAMS:
            write_msg(f, 1, 'QNf', [t, pname, float(pval)])
            t += 1000

        # Initial MSG
        t = START_US + 50000
        write_msg(f, 9, 'QZ', [t, 'ArduCopter V4.5.7 (abcdef12)'])
        t += 1000
        write_msg(f, 9, 'QZ', [t, 'EKF3 IMU0 started on core 0'])
        t += 1000
        write_msg(f, 9, 'QZ', [t, 'EKF3 IMU1 started on core 1'])

        # Main data loop
        for i in range(N):
            t = START_US + 100000 + i * DT_US
            primary = 0 if i < LANE_SWITCH_SAMPLE else 1
            gps_ok = not (GPS_OUTAGE_START <= i < GPS_OUTAGE_END)
            alt = altitude(i)

            # GPS (5 Hz — every 10th sample)
            if i % 10 == 0:
                status = 3 if gps_ok else 0
                hdop = 1.2 if gps_ok else 99.9
                nsats = 12 if gps_ok else 0
                gms = 345600000 + (i * DT_US) // 1000  # ms into GPS week
                gwk = 2300
                write_msg(f, 2, 'QBBIHBf',
                          [t, 0, status, gms, gwk, nsats, hdop])

            # CTUN (25 Hz — every 2nd sample)
            if i % 2 == 0:
                dalt = 50.0 if GROUND1_END <= i < CRUISE_END else 0.0
                write_msg(f, 7, 'Qff', [t, alt, dalt])

            # STAT (1 Hz — every 50th sample)
            if i % 50 == 0:
                write_msg(f, 8, 'QBB', [t, primary, 1])

            # Lane-switch MSG
            if i == LANE_SWITCH_SAMPLE:
                write_msg(f, 9, 'QZ', [t, 'EKF3 lane switch 0>1'])

            # XKF1 / XKF4 for both cores
            for core in (0, 1):
                innov = []
                var = []
                for field, truth, cfg, proc in CHANNELS_VP:
                    actual_std = math.sqrt(truth ** 2 + proc ** 2)
                    rep_var = cfg ** 2 + proc ** 2

                    if field in GPS_FIELDS and not gps_ok:
                        val = float('nan')
                    else:
                        val = random.gauss(0, actual_std * noise_scale(i))
                        val += ground_bias(field, i)

                    innov.append(val)
                    var.append(rep_var)

                write_msg(f, 3, 'QBffffff', [t, core] + innov)
                write_msg(f, 5, 'QBffffff', [t, core] + var)

            # XKF2 / XKF5 for both cores
            for core in (0, 1):
                innov = []
                var = []
                for field, truth, cfg, proc in CHANNELS_MY:
                    actual_std = math.sqrt(truth ** 2 + proc ** 2)
                    rep_var = cfg ** 2 + proc ** 2

                    val = random.gauss(0, actual_std * noise_scale(i))
                    val += ground_bias(field, i)

                    # Mag bias on core 0 MagZ only
                    if (field == 'IMZ' and core == 0
                            and MAG_BIAS_START <= i < MAG_BIAS_END):
                        val += MAG_BIAS_VALUE

                    innov.append(val)
                    var.append(rep_var)

                write_msg(f, 4, 'QBffff', [t, core] + innov)
                write_msg(f, 6, 'QBffff', [t, core] + var)

    print(f'Generated flight.bin: {N} samples, 2 EKF cores')
    print(f'Cruise: {TAKEOFF_END}-{CRUISE_END}, '
          f'Lane switch: {LANE_SWITCH_SAMPLE}, '
          f'GPS outage: {GPS_OUTAGE_START}-{GPS_OUTAGE_END}')


if __name__ == '__main__':
    main()
