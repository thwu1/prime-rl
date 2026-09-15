#!/usr/bin/env python3
"""GNSS broadcast ephemeris processing pipeline."""

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta

# Physical constants
MU_GPS = 3.986005e14
MU_GAL = 3.986004418e14
OMEGA_E_DOT = 7.2921151467e-5
C_LIGHT = 299792458.0

# Valid orbit radius ranges (m)
GPS_ORBIT_MIN = 24000e3
GPS_ORBIT_MAX = 28000e3
GAL_ORBIT_MIN = 27000e3
GAL_ORBIT_MAX = 32000e3

# Nominal radii for RMS computation (m)
GPS_NOMINAL_RADIUS = 26560e3
GAL_NOMINAL_RADIUS = 29600e3


def detect_rinex_version(filepath):
    """Detect RINEX version from file header."""
    with open(filepath) as f:
        first_line = f.readline()
    version_str = first_line[:9].strip()
    try:
        version = float(version_str)
    except ValueError:
        return None
    return version


def tokenize_rinex_line(line):
    """Split a RINEX data line into float tokens, handling D/d/E/e and sign-delimited."""
    line = line.replace('D', 'E').replace('d', 'e')
    tokens = []
    i = 0
    n = len(line)
    while i < n:
        if line[i] == ' ':
            i += 1
            continue
        start = i
        if line[i] in '+-':
            i += 1
        while i < n and line[i] != ' ':
            if line[i] in '+-' and i > start:
                if i > 0 and line[i - 1] in 'Ee':
                    i += 1
                    continue
                else:
                    break
            i += 1
        token = line[start:i]
        if token:
            try:
                tokens.append(float(token))
            except ValueError:
                pass
    return tokens


def _gps_week_and_tow(year, month, day, hour, minute, second):
    """Compute GPS week number and time of week from calendar date."""
    dt = datetime(year, month, day, hour, minute, second)
    gps_epoch = datetime(1980, 1, 6)
    delta = dt - gps_epoch
    total_seconds = delta.total_seconds()
    week = int(total_seconds // 604800)
    tow = total_seconds - week * 604800
    return week, tow


def _gps_to_calendar(gps_week, tow):
    """Convert GPS week and TOW to calendar date."""
    gps_epoch = datetime(1980, 1, 6)
    dt = gps_epoch + timedelta(seconds=gps_week * 604800 + tow)
    return dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second


def _compute_mjd(year, month, day):
    """Compute Modified Julian Day from calendar date."""
    y, m = year, month
    if m <= 2:
        y -= 1
        m += 12
    A = y // 100
    B = 2 - A + A // 4
    JD = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + B - 1524.5
    return int(JD - 2400000.5)


def parse_rinex305_nav(filepath):
    """Parse a RINEX 3.05 navigation file and return ephemeris dict keyed by (sat, Toe)."""
    ephemerides = {}
    header_done = False

    with open(filepath) as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i]
        if not header_done:
            if 'END OF HEADER' in line:
                header_done = True
            i += 1
            continue

        if len(line) < 23:
            i += 1
            continue

        sys_char = line[0]
        if sys_char not in 'GE':
            if sys_char in 'RJCIS':
                n_bo = 3 if sys_char in 'RS' else 7
                i += 1 + n_bo
            else:
                i += 1
            continue

        try:
            prn = int(line[1:3])
        except ValueError:
            i += 1
            continue

        sat_id = f"{sys_char}{prn:02d}"

        try:
            year = int(line[3:8].strip())
            month = int(line[8:11].strip())
            day = int(line[11:14].strip())
            hour = int(line[14:17].strip())
            minute = int(line[17:20].strip())
            second = int(line[20:23].strip())
        except (ValueError, IndexError):
            i += 1
            continue

        clock_vals = tokenize_rinex_line(line[23:])
        while len(clock_vals) < 3:
            clock_vals.append(0.0)

        gps_week, toc_tow = _gps_week_and_tow(year, month, day, hour, minute, second)

        n_bo_lines = 7
        bo_values = []
        for j in range(n_bo_lines):
            if i + 1 + j >= len(lines):
                break
            bo_values.extend(tokenize_rinex_line(lines[i + 1 + j]))

        while len(bo_values) < 28:
            bo_values.append(0.0)

        eph = {
            'satellite': sat_id,
            'constellation': sys_char,
            'af0': clock_vals[0], 'af1': clock_vals[1], 'af2': clock_vals[2],
            'Toc_tow': toc_tow,
            'gps_week': gps_week,
            'IODE': bo_values[0], 'Crs': bo_values[1],
            'Delta_n': bo_values[2], 'M0': bo_values[3],
            'Cuc': bo_values[4], 'e': bo_values[5],
            'Cus': bo_values[6], 'sqrt_A': bo_values[7],
            'Toe': bo_values[8], 'Cic': bo_values[9],
            'OMEGA0': bo_values[10], 'Cis': bo_values[11],
            'i0': bo_values[12], 'Crc': bo_values[13],
            'omega': bo_values[14], 'OMEGA_DOT': bo_values[15],
            'IDOT': bo_values[16],
        }

        key = (sat_id, bo_values[8])
        if key not in ephemerides:
            ephemerides[key] = eph

        i += 1 + n_bo_lines

    return ephemerides


def parse_rinex211_nav(filepath):
    """Parse a RINEX 2.11 GPS navigation file. Returns (ephemerides, header_info, raw_sats)."""
    header_info = {
        'comments': [],
        'ion_alpha': [],
        'ion_beta': [],
        'delta_utc': {},
        'leap_seconds': 0,
        'pgm': '',
        'agency': '',
        'date': '',
    }
    ephemerides = {}
    raw_sats = []
    header_done = False

    with open(filepath) as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i]

        if not header_done:
            label = line[60:80].strip() if len(line) >= 60 else ''

            if label == 'PGM / RUN BY / DATE':
                header_info['pgm'] = line[:20].rstrip()
                header_info['agency'] = line[20:40].rstrip()
                header_info['date'] = line[40:60].rstrip()
            elif label == 'COMMENT':
                header_info['comments'].append(line[:60].rstrip())
            elif label == 'ION ALPHA':
                vals_str = line[:60].replace('D', 'E').replace('d', 'e')
                header_info['ion_alpha'] = [
                    float(vals_str[2 + j * 12:2 + (j + 1) * 12]) for j in range(4)
                ]
            elif label == 'ION BETA':
                vals_str = line[:60].replace('D', 'E').replace('d', 'e')
                header_info['ion_beta'] = [
                    float(vals_str[2 + j * 12:2 + (j + 1) * 12]) for j in range(4)
                ]
            elif label.startswith('DELTA-UTC'):
                vals_str = line[:60].replace('D', 'E').replace('d', 'e')
                a0 = float(vals_str[3:22])
                a1 = float(vals_str[22:41])
                t_ref = int(vals_str[41:50].strip())
                w_ref = int(vals_str[50:59].strip())
                header_info['delta_utc'] = {'A0': a0, 'A1': a1, 'T': t_ref, 'W': w_ref}
            elif label == 'LEAP SECONDS':
                header_info['leap_seconds'] = int(line[:6].strip())
            elif label == 'END OF HEADER':
                header_done = True

            i += 1
            continue

        if len(line) < 22:
            i += 1
            continue

        try:
            prn = int(line[0:2].strip())
        except ValueError:
            i += 1
            continue

        try:
            yr = int(line[3:5].strip())
            month = int(line[6:8].strip())
            day = int(line[9:11].strip())
            hour = int(line[12:14].strip())
            minute = int(line[15:17].strip())
            sec_str = line[17:22].strip()
            second = int(float(sec_str))
        except (ValueError, IndexError):
            i += 1
            continue

        year = 1900 + yr if yr >= 80 else 2000 + yr

        clock_vals = tokenize_rinex_line(line[22:])
        while len(clock_vals) < 3:
            clock_vals.append(0.0)

        gps_week, toc_tow = _gps_week_and_tow(year, month, day, hour, minute, second)

        bo_values = []
        for j in range(7):
            if i + 1 + j >= len(lines):
                break
            bo_values.extend(tokenize_rinex_line(lines[i + 1 + j]))

        while len(bo_values) < 28:
            bo_values.append(0.0)

        sat_id = f"G{prn:02d}"
        eph = {
            'satellite': sat_id,
            'constellation': 'G',
            'af0': clock_vals[0], 'af1': clock_vals[1], 'af2': clock_vals[2],
            'Toc_tow': toc_tow,
            'gps_week': gps_week,
            'IODE': bo_values[0], 'Crs': bo_values[1],
            'Delta_n': bo_values[2], 'M0': bo_values[3],
            'Cuc': bo_values[4], 'e': bo_values[5],
            'Cus': bo_values[6], 'sqrt_A': bo_values[7],
            'Toe': bo_values[8], 'Cic': bo_values[9],
            'OMEGA0': bo_values[10], 'Cis': bo_values[11],
            'i0': bo_values[12], 'Crc': bo_values[13],
            'omega': bo_values[14], 'OMEGA_DOT': bo_values[15],
            'IDOT': bo_values[16],
        }

        raw_sats.append({
            'prn': prn, 'year': year, 'month': month, 'day': day,
            'hour': hour, 'minute': minute, 'second': second,
            'af0': clock_vals[0], 'af1': clock_vals[1], 'af2': clock_vals[2],
            'bo_values': bo_values,
        })

        key = (sat_id, bo_values[8])
        if key not in ephemerides:
            ephemerides[key] = eph

        i += 1 + 7

    return ephemerides, header_info, raw_sats


def compute_satellite_position(eph, tow):
    """Compute satellite ECEF position from broadcast ephemeris."""
    constellation = eph['constellation']
    mu = MU_GPS if constellation == 'G' else MU_GAL

    A = eph['sqrt_A'] ** 2
    n0 = math.sqrt(mu / A**3)
    n = n0 + eph['Delta_n']

    tk = tow - eph['Toe']
    if tk > 302400:
        tk -= 604800
    elif tk < -302400:
        tk += 604800

    Mk = eph['M0'] + n * tk

    Ek = Mk
    for _ in range(30):
        Ek_new = Mk + eph['e'] * math.sin(Ek)
        if abs(Ek_new - Ek) < 1e-15:
            break
        Ek = Ek_new
    Ek = Ek_new

    sin_Ek = math.sin(Ek)
    cos_Ek = math.cos(Ek)

    denom = 1.0 - eph['e'] * cos_Ek
    sin_vk = math.sqrt(1.0 - eph['e']**2) * sin_Ek / denom
    cos_vk = (cos_Ek - eph['e']) / denom
    vk = math.atan2(sin_vk, cos_vk)

    Phi_k = vk + eph['omega']
    sin2Phi = math.sin(2.0 * Phi_k)
    cos2Phi = math.cos(2.0 * Phi_k)

    delta_uk = eph['Cus'] * sin2Phi + eph['Cuc'] * cos2Phi
    delta_rk = eph['Crs'] * sin2Phi + eph['Crc'] * cos2Phi
    delta_ik = eph['Cis'] * sin2Phi + eph['Cic'] * cos2Phi

    uk = Phi_k + delta_uk
    rk = A * (1.0 - eph['e'] * cos_Ek) + delta_rk
    ik = eph['i0'] + delta_ik + eph['IDOT'] * tk

    xk_prime = rk * math.cos(uk)
    yk_prime = rk * math.sin(uk)

    OMEGA_k = eph['OMEGA0'] + (eph['OMEGA_DOT'] - OMEGA_E_DOT) * tk - OMEGA_E_DOT * eph['Toe']

    cos_OMEGA = math.cos(OMEGA_k)
    sin_OMEGA = math.sin(OMEGA_k)
    cos_ik = math.cos(ik)
    sin_ik = math.sin(ik)

    xk = xk_prime * cos_OMEGA - yk_prime * cos_ik * sin_OMEGA
    yk = xk_prime * sin_OMEGA + yk_prime * cos_ik * cos_OMEGA
    zk = yk_prime * sin_ik

    dt_clk = tow - eph['Toc_tow']
    if dt_clk > 302400:
        dt_clk -= 604800
    elif dt_clk < -302400:
        dt_clk += 604800

    clock_correction = eph['af0'] + eph['af1'] * dt_clk + eph['af2'] * dt_clk**2

    F = -2.0 * math.sqrt(mu) / (C_LIGHT**2)
    rel_corr = F * eph['e'] * eph['sqrt_A'] * sin_Ek

    orbit_radius = math.sqrt(xk**2 + yk**2 + zk**2)

    return {
        'x_m': xk, 'y_m': yk, 'z_m': zk,
        'clock_correction_s': clock_correction,
        'relativistic_correction_s': rel_corr,
        'orbit_radius_m': orbit_radius,
    }


def is_anomalous(constellation, orbit_radius):
    """Check if orbit radius is outside valid range for constellation."""
    if constellation == 'G':
        return orbit_radius < GPS_ORBIT_MIN or orbit_radius > GPS_ORBIT_MAX
    elif constellation == 'E':
        return orbit_radius < GAL_ORBIT_MIN or orbit_radius > GAL_ORBIT_MAX
    return False


def cmd_process(args):
    """Process command: parse nav files, compute positions, store in SQLite, generate report."""
    all_ephem = {}

    for nav_file in args.nav:
        version = detect_rinex_version(nav_file)
        if version is not None and version < 3.0:
            ephem, _, _ = parse_rinex211_nav(nav_file)
        else:
            ephem = parse_rinex305_nav(nav_file)

        for key, eph in ephem.items():
            if key not in all_ephem:
                all_ephem[key] = eph

    results = []
    for (sat_id, toe), eph in sorted(all_ephem.items()):
        gps_week = eph['gps_week']
        for offset in [0, 300, 600]:
            tow = toe + offset
            week = gps_week
            if tow >= 604800:
                tow -= 604800
                week += 1
            pos = compute_satellite_position(eph, tow)
            anomaly = 1 if is_anomalous(eph['constellation'], pos['orbit_radius_m']) else 0
            results.append({
                'satellite': sat_id,
                'gps_week': week,
                'tow': tow,
                **pos,
                'anomaly_flag': anomaly,
            })

    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    if os.path.exists(args.db):
        os.remove(args.db)

    conn = sqlite3.connect(args.db)
    c = conn.cursor()
    c.execute('''CREATE TABLE positions (
        satellite TEXT NOT NULL,
        gps_week INTEGER NOT NULL,
        tow REAL NOT NULL,
        x_m REAL NOT NULL,
        y_m REAL NOT NULL,
        z_m REAL NOT NULL,
        clock_correction_s REAL NOT NULL,
        relativistic_correction_s REAL NOT NULL,
        orbit_radius_m REAL NOT NULL,
        anomaly_flag INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (satellite, tow)
    )''')

    for r in results:
        c.execute(
            '''INSERT INTO positions
            (satellite, gps_week, tow, x_m, y_m, z_m, clock_correction_s,
             relativistic_correction_s, orbit_radius_m, anomaly_flag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (r['satellite'], r['gps_week'], r['tow'], r['x_m'], r['y_m'], r['z_m'],
             r['clock_correction_s'], r['relativistic_correction_s'],
             r['orbit_radius_m'], r['anomaly_flag']))

    conn.commit()
    conn.close()

    satellites_processed = sorted(set(r['satellite'] for r in results))
    anomalous_sats = sorted(set(
        r['satellite'] for r in results if r['anomaly_flag'] == 1
    ))

    rms_deviation = {}
    for sat in satellites_processed:
        if sat in anomalous_sats:
            continue
        constellation = sat[0]
        nominal = GPS_NOMINAL_RADIUS if constellation == 'G' else GAL_NOMINAL_RADIUS
        deviations = [
            (r['orbit_radius_m'] - nominal)
            for r in results
            if r['satellite'] == sat and r['anomaly_flag'] == 0
        ]
        if deviations:
            rms = math.sqrt(sum(d**2 for d in deviations) / len(deviations))
            rms_deviation[sat] = rms

    report = {
        'satellites_processed': satellites_processed,
        'total_positions': len(results),
        'anomalous_satellites': anomalous_sats,
        'rms_radius_deviation': rms_deviation,
    }

    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Processed {len(results)} positions for {len(satellites_processed)} satellites")


def format_d19_12(value):
    """Format a value in D19.12-like notation (19 chars wide)."""
    if value == 0.0:
        return "  .000000000000D+00"
    sign = '-' if value < 0 else ' '
    av = abs(value)
    exp = int(math.floor(math.log10(av))) + 1
    mantissa = av / (10.0 ** exp)

    mant_str = f".{mantissa:.12f}"[1:]
    if len(mant_str) > 13:
        mant_str = mant_str[:13]

    exp_sign = '+' if exp >= 0 else '-'
    exp_str = f"{abs(exp):02d}"

    result = f"{sign}{mant_str}D{exp_sign}{exp_str}"
    if len(result) < 19:
        result = ' ' * (19 - len(result)) + result
    return result[:19]


def format_d12_4(value):
    """Format a value in D12.4 notation (12 chars wide)."""
    if value == 0.0:
        return "  .0000D+00 "[:12]
    sign = '-' if value < 0 else ' '
    av = abs(value)
    exp = int(math.floor(math.log10(av))) + 1
    mantissa = av / (10.0 ** exp)

    mant_str = f"{mantissa:.4f}"[1:]

    exp_sign = '+' if exp >= 0 else '-'
    exp_str = f"{abs(exp):02d}"

    result = f"{sign}{mant_str}D{exp_sign}{exp_str}"
    if len(result) < 12:
        result = ' ' * (12 - len(result)) + result
    return result[:12]


def cmd_convert(args):
    """Convert RINEX 2.11 GPS navigation file to 3.05 format."""
    _, header_info, raw_sats = parse_rinex211_nav(args.input)

    os.makedirs(
        os.path.dirname(args.output) if os.path.dirname(args.output) else '.', exist_ok=True
    )

    with open(args.output, 'w') as f:
        ver_line = f"{'3.05':>9s}{'':11s}N: GNSS NAV DATA    G: GPS{'':14s}RINEX VERSION / TYPE\n"
        f.write(ver_line)

        now = datetime.utcnow()
        date_str = now.strftime("%Y%m%d %H%M%S") + " UTC"
        pgm = "rnx_converter"
        agency = "Converter"
        pgm_line = f"{pgm:<20s}{agency:<20s}{date_str:<20s}PGM / RUN BY / DATE\n"
        f.write(pgm_line)

        for c_text in header_info['comments']:
            f.write(f"{c_text:<60s}COMMENT{'':13s}\n")

        if header_info['ion_alpha']:
            vals = ''.join(format_d12_4(v) for v in header_info['ion_alpha'])
            f.write(f"GPSA {vals}{'':7s}IONOSPHERIC CORR{'':4s}\n")
        if header_info['ion_beta']:
            vals = ''.join(format_d12_4(v) for v in header_info['ion_beta'])
            f.write(f"GPSB {vals}{'':7s}IONOSPHERIC CORR{'':4s}\n")

        if header_info['delta_utc']:
            du = header_info['delta_utc']
            a0_str = f"{du['A0']:>17.10E}".replace('E', 'D')
            a1_str = f"{du['A1']:>16.9E}".replace('E', 'D')
            t_str = f"{du['T']:6d}"
            w_str = f"{du['W']:5d}"
            tc_data = f"GPUT {a0_str}{a1_str}{t_str}{w_str}"
            padding = 60 - len(tc_data)
            if padding > 0:
                tc_data += ' ' * padding
            f.write(f"{tc_data}TIME SYSTEM CORR{'':4s}\n")

        f.write(f"{header_info['leap_seconds']:6d}{'':54s}LEAP SECONDS{'':8s}\n")
        f.write(f"{'':60s}END OF HEADER{'':7s}\n")

        for sat in raw_sats:
            prn = sat['prn']
            epoch_str = (
                f"G{prn:02d} {sat['year']:4d} {sat['month']:02d} "
                f"{sat['day']:02d} {sat['hour']:02d} {sat['minute']:02d} "
                f"{sat['second']:02d}"
            )
            af0_str = format_d19_12(sat['af0'])
            af1_str = format_d19_12(sat['af1'])
            af2_str = format_d19_12(sat['af2'])
            f.write(f"{epoch_str}{af0_str}{af1_str}{af2_str}\n")

            bv = sat['bo_values']
            for line_idx in range(7):
                start = line_idx * 4
                vals_on_line = bv[start:start + 4]
                while len(vals_on_line) < 4:
                    vals_on_line.append(0.0)
                val_strs = ''.join(format_d19_12(v) for v in vals_on_line)
                f.write(f"    {val_strs}\n")

    print(f"Converted {len(raw_sats)} satellites -> {args.output}")


def cmd_export(args):
    """Export non-anomalous positions to SP3c format."""
    conn = sqlite3.connect(args.db)
    c = conn.cursor()

    c.execute("""
        SELECT satellite, gps_week, tow, x_m, y_m, z_m, clock_correction_s
        FROM positions WHERE anomaly_flag = 0
        ORDER BY gps_week, tow, satellite
    """)
    rows = c.fetchall()
    conn.close()

    # Group by epoch (gps_week, tow)
    epochs = {}
    satellites = set()
    for sat, week, tow, x, y, z, clk in rows:
        key = (week, tow)
        if key not in epochs:
            epochs[key] = []
        epochs[key].append((sat, x, y, z, clk))
        satellites.add(sat)

    sorted_epochs = sorted(epochs.keys())
    sat_list = sorted(satellites)
    n_epochs = len(sorted_epochs)
    n_sats = len(sat_list)

    # First epoch for header
    first_week, first_tow = sorted_epochs[0]
    yr, mo, dy, hr, mn, sc = _gps_to_calendar(first_week, first_tow)
    mjd = _compute_mjd(yr, mo, dy)
    frac_day = (hr * 3600 + mn * 60 + sc) / 86400.0

    os.makedirs(os.path.dirname(args.sp3), exist_ok=True)

    with open(args.sp3, 'w') as f:
        # Line 1: version
        f.write(f"#cP{yr:4d} {mo:2d} {dy:2d} {hr:2d} {mn:2d} {sc:11.8f}"
                f"{n_epochs:7d} ORBIT WGS84 BCT GNSS\n")

        # Line 2: GPS week, SOW, interval, MJD, fractional day
        f.write(f"## {first_week:4d} {first_tow:15.8f}   300.00000000"
                f" {mjd:5d} {frac_day:15.13f}\n")

        # Lines 3-7: satellite list (5 lines, 17 per line)
        for line_idx in range(5):
            sat_slots = []
            for j in range(17):
                idx = line_idx * 17 + j
                if idx < n_sats:
                    sat_slots.append(f"{sat_list[idx]:>3s}")
                else:
                    sat_slots.append("  0")
            if line_idx == 0:
                f.write(f"+  {n_sats:3d}   " + "".join(sat_slots) + "\n")
            else:
                f.write("+        " + "".join(sat_slots) + "\n")

        # Lines 8-12: accuracy exponents (all zero)
        for _ in range(5):
            f.write("++       " + "  0" * 17 + "\n")

        # Lines 13-14: %c format descriptor
        f.write("%c M  cc GPS ccc cccc cccc cccc cccc ccccc ccccc ccccc ccccc\n")
        f.write("%c cc cc ccc ccc cccc cccc cccc cccc ccccc ccccc ccccc ccccc\n")

        # Lines 15-16: %f base numbers
        f.write("%f  1.2500000  1.025000000  0.00000000000  0.000000000000000\n")
        f.write("%f  0.0000000  0.000000000  0.00000000000  0.000000000000000\n")

        # Lines 17-18: %i integers
        f.write("%i    0    0    0    0      0      0      0      0         0\n")
        f.write("%i    0    0    0    0      0      0      0      0         0\n")

        # Lines 19-22: comments (4 minimum)
        f.write("/* GNSS broadcast ephemeris positions\n")
        f.write("/* Generated by gnss_pipeline export command\n")
        f.write("/* Non-anomalous satellites only\n")
        f.write("/* WGS-84 ECEF coordinates, clock in microseconds\n")

        # Epoch records
        for week, tow in sorted_epochs:
            eyr, emo, edy, ehr, emn, esc = _gps_to_calendar(week, tow)
            f.write(f"*  {eyr:4d} {emo:2d} {edy:2d} {ehr:2d} {emn:2d}"
                    f" {float(esc):11.8f}\n")
            for sat, x, y, z, clk in sorted(epochs[(week, tow)]):
                x_km = x / 1000.0
                y_km = y / 1000.0
                z_km = z / 1000.0
                clk_us = clk * 1e6
                f.write(f"P{sat:>3s}{x_km:14.6f}{y_km:14.6f}"
                        f"{z_km:14.6f}{clk_us:14.6f}\n")

        f.write("EOF\n")

    print(f"Exported {n_epochs} epochs for {n_sats} satellites to {args.sp3}")


def _parse_sp3(filepath):
    """Parse SP3 file and return dict of (sat, tow) -> (x_km, y_km, z_km, clk_us)."""
    data = {}
    current_tow = None
    current_week = None

    with open(filepath) as f:
        for line in f:
            if line.startswith('*'):
                parts = line[2:].split()
                yr = int(parts[0])
                mo = int(parts[1])
                dy = int(parts[2])
                hr = int(parts[3])
                mn = int(parts[4])
                sc = int(float(parts[5]))
                current_week, current_tow = _gps_week_and_tow(yr, mo, dy, hr, mn, sc)
            elif line.startswith('P') and current_tow is not None:
                sat = line[1:4].strip()
                vals = line[4:].split()
                x_km = float(vals[0])
                y_km = float(vals[1])
                z_km = float(vals[2])
                clk_us = float(vals[3])
                data[(sat, current_tow)] = (x_km, y_km, z_km, clk_us)

    return data


def cmd_validate(args):
    """Cross-validate database against SP3 file."""
    conn = sqlite3.connect(args.db)
    c = conn.cursor()

    # Get non-anomalous satellites
    c.execute("""
        SELECT DISTINCT satellite FROM positions
        WHERE anomaly_flag = 0 ORDER BY satellite
    """)
    sats = [row[0] for row in c.fetchall()]

    # Parse SP3 file
    sp3_data = _parse_sp3(args.sp3)

    result = {"satellites": {}, "overall_pass": True}

    for sat in sats:
        c.execute("""
            SELECT tow, x_m, y_m, z_m, clock_correction_s
            FROM positions WHERE satellite=? AND anomaly_flag=0
            ORDER BY tow
        """, (sat,))
        db_rows = c.fetchall()

        # Check SP3 match
        max_err = 0.0
        sp3_match = True
        for tow, x, y, z, clk in db_rows:
            sp3_pos = sp3_data.get((sat, tow))
            if sp3_pos is None:
                sp3_match = False
                continue
            err = math.sqrt(
                (sp3_pos[0] - x / 1000.0) ** 2
                + (sp3_pos[1] - y / 1000.0) ** 2
                + (sp3_pos[2] - z / 1000.0) ** 2
            )
            max_err = max(max_err, err)
            if err > 0.001:
                sp3_match = False

        # Compute inter-epoch velocities
        velocities = []
        for i in range(1, len(db_rows)):
            dt = db_rows[i][0] - db_rows[i - 1][0]
            dx = db_rows[i][1] - db_rows[i - 1][1]
            dy = db_rows[i][2] - db_rows[i - 1][2]
            dz = db_rows[i][3] - db_rows[i - 1][3]
            v = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2) / dt / 1000.0  # km/s
            velocities.append(round(v, 6))

        velocity_anomaly = any(v < 2.0 or v > 5.0 for v in velocities)

        # Compute clock drift rates
        drift_rates = []
        for i in range(1, len(db_rows)):
            dt = db_rows[i][0] - db_rows[i - 1][0]
            dclk = db_rows[i][4] - db_rows[i - 1][4]
            rate = dclk / dt
            drift_rates.append(rate)

        clock_drift_anomaly = any(abs(r) > 1e-6 for r in drift_rates)

        sat_result = {
            "sp3_match": sp3_match,
            "max_position_error_km": round(max_err, 9),
            "velocities_km_s": velocities,
            "velocity_anomaly": velocity_anomaly,
            "clock_drift_rates": drift_rates,
            "clock_drift_anomaly": clock_drift_anomaly,
        }

        result["satellites"][sat] = sat_result

        if not sp3_match or velocity_anomaly or clock_drift_anomaly:
            result["overall_pass"] = False

    conn.close()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Validation: {'PASS' if result['overall_pass'] else 'FAIL'}")


def main():
    parser = argparse.ArgumentParser(description='GNSS Navigation Pipeline')
    subparsers = parser.add_subparsers(dest='command')

    p_process = subparsers.add_parser('process', help='Process navigation files')
    p_process.add_argument('--nav', nargs='+', required=True, help='RINEX nav files')
    p_process.add_argument('--db', required=True, help='Output SQLite database')
    p_process.add_argument('--report', required=True, help='Output JSON report')

    p_convert = subparsers.add_parser('convert', help='Convert RINEX 2.11 to 3.05')
    p_convert.add_argument('--input', required=True, help='Input RINEX 2.11 file')
    p_convert.add_argument('--output', required=True, help='Output RINEX 3.05 file')

    p_export = subparsers.add_parser('export', help='Export to SP3c format')
    p_export.add_argument('--db', required=True, help='Input SQLite database')
    p_export.add_argument('--sp3', required=True, help='Output SP3c file')

    p_validate = subparsers.add_parser('validate', help='Cross-validate DB and SP3')
    p_validate.add_argument('--db', required=True, help='Input SQLite database')
    p_validate.add_argument('--sp3', required=True, help='Input SP3c file')
    p_validate.add_argument('--output', required=True, help='Output validation JSON')

    args = parser.parse_args()

    if args.command == 'process':
        cmd_process(args)
    elif args.command == 'convert':
        cmd_convert(args)
    elif args.command == 'export':
        cmd_export(args)
    elif args.command == 'validate':
        cmd_validate(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
