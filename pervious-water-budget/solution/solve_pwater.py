#!/usr/bin/env python3
"""
Complete HSPF PWATER solver: parses UCI file, simulates pervious land water budget
for multiple segments, produces per-segment and aggregate outputs in CSV, HDF5,
and SQLite formats with water balance tracking.
"""

import json
import math
import re
import sqlite3
import numpy as np
import pandas as pd
import h5py
from datetime import datetime, timedelta


# == UCI Parser ================================================================

def parse_uci(filepath):
    """Parse HSPF UCI file to extract simulation info and PERLND parameters."""
    with open(filepath) as f:
        lines = f.readlines()

    siminfo = {}
    segments = {}

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if stripped == 'GLOBAL':
            i += 1
            i, siminfo = _parse_global(lines, i)
        elif stripped == 'PERLND':
            i += 1
            i, segments = _parse_perlnd(lines, i)
        else:
            i += 1

    return siminfo, segments


def _parse_global(lines, i):
    """Parse GLOBAL section for simulation period and unit system."""
    siminfo = {}
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if stripped == 'END GLOBAL':
            i += 1
            break

        if 'START' in line and 'END' in line:
            parts = line.split()
            try:
                si = parts.index('START')
                ei = parts.index('END')
                start_parts = parts[si+1:ei]
                end_parts = parts[ei+1:]

                if len(start_parts) >= 3:
                    syr, smo, sda = int(start_parts[0]), int(start_parts[1]), int(start_parts[2])
                elif len(start_parts) == 1:
                    syr, smo, sda = int(start_parts[0]), 1, 1
                siminfo['start'] = f"{syr:04d}-{smo:02d}-{sda:02d} 00:00:00"

                if len(end_parts) >= 3:
                    eyr, emo, eda = int(end_parts[0]), int(end_parts[1]), int(end_parts[2])
                elif len(end_parts) == 1:
                    eyr, emo, eda = int(end_parts[0]), 1, 1
                siminfo['stop'] = f"{eyr:04d}-{emo:02d}-{eda:02d} 00:00:00"
            except (ValueError, IndexError):
                pass

        if 'UNIT SYSTEM' in line:
            parts = line.split('UNIT SYSTEM')
            if len(parts) > 1:
                siminfo['units'] = int(parts[1].strip().split()[0])

        i += 1
    return i, siminfo


def _parse_perlnd(lines, i):
    """Parse PERLND section for all segments."""
    segments = {}
    current_table = None
    header_names = None

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if stripped == 'END PERLND':
            i += 1
            break

        if stripped in ('PWAT-PARM1', 'PWAT-PARM2', 'PWAT-PARM3', 'PWAT-PARM4',
                        'PWAT-STATE1', 'MON-INTERCEP', 'ACTIVITY', 'GEN-INFO'):
            current_table = stripped
            header_names = None
            i += 1
            continue

        if stripped.startswith('END '):
            current_table = None
            header_names = None
            i += 1
            continue

        if stripped.startswith('***') or stripped.startswith('<'):
            if current_table and '***' in line:
                hdr = _extract_header_names(line, current_table)
                if hdr:
                    header_names = hdr
            i += 1
            continue

        if current_table and not stripped.startswith('#'):
            if current_table in ('PWAT-PARM1', 'PWAT-PARM2', 'PWAT-PARM3',
                                  'PWAT-PARM4', 'PWAT-STATE1'):
                _parse_param_line(line, current_table, header_names, segments)
            elif current_table == 'MON-INTERCEP':
                _parse_monthly_line(line, segments)

        i += 1

    return i, segments


_TABLE_FIELDS = {
    'PWAT-PARM1': ['CSNOFG', 'RTOPFG', 'UZFG', 'VCSFG', 'VUZFG', 'VNNFG', 'VIFWFG', 'VIRCFG', 'VLEFG'],
    'PWAT-PARM2': ['FOREST', 'LZSN', 'INFILT', 'LSUR', 'SLSUR', 'KVARY', 'AGWRC'],
    'PWAT-PARM3': ['PETMAX', 'PETMIN', 'INFEXP', 'INFILD', 'DEEPFR', 'BASETP', 'AGWETP'],
    'PWAT-PARM4': ['CEPSC', 'UZSN', 'NSUR', 'INTFW', 'IRC', 'LZETP'],
    'PWAT-STATE1': ['CEPS', 'SURS', 'UZS', 'IFWS', 'LZS', 'AGWS', 'GWVS'],
}

_INT_FIELDS = {'CSNOFG', 'RTOPFG', 'UZFG', 'VCSFG', 'VUZFG', 'VNNFG',
               'VIFWFG', 'VIRCFG', 'VLEFG', 'IFFCFG', 'IFRDFG'}


def _extract_header_names(line, table):
    if table in _TABLE_FIELDS:
        return _TABLE_FIELDS[table]
    return None


def _parse_param_line(line, table, header_names, segments):
    stripped = line.strip()
    if not stripped or stripped.startswith('***') or stripped.startswith('<'):
        return

    tokens = stripped.split()
    if not tokens or not tokens[0].isdigit():
        return

    seg_num = int(tokens[0])
    seg_id = f"P{seg_num:03d}"
    values = tokens[1:]

    if seg_id not in segments:
        segments[seg_id] = {'parameters': {}, 'states': {}, 'monthly_cepsc': None}

    field_names = _TABLE_FIELDS.get(table, header_names or [])

    for j, name in enumerate(field_names):
        if j < len(values):
            try:
                val = float(values[j])
                if name in _INT_FIELDS:
                    val = int(val)
            except ValueError:
                continue

            if table == 'PWAT-STATE1':
                segments[seg_id]['states'][name] = val
            else:
                segments[seg_id]['parameters'][name] = val


def _parse_monthly_line(line, segments):
    stripped = line.strip()
    if not stripped or stripped.startswith('***') or stripped.startswith('<'):
        return

    tokens = stripped.split()
    if not tokens or not tokens[0].isdigit():
        return

    seg_num = int(tokens[0])
    seg_id = f"P{seg_num:03d}"
    values = [float(v) for v in tokens[1:] if not v.startswith('*')]

    if seg_id in segments and len(values) == 12:
        segments[seg_id]['monthly_cepsc'] = values


# == Monthly Interpolation =====================================================

def interpolate_monthly(siminfo, monthly_values, steps):
    """Linearly interpolate monthly values to hourly, recomputed daily."""
    import calendar
    start = datetime.strptime(siminfo["start"], "%Y-%m-%d %H:%M:%S")
    result = np.zeros(steps)
    current_val = monthly_values[start.month - 1]

    for step in range(steps):
        current_time = start + timedelta(minutes=step * 60)
        if step == 0 or (current_time.hour == 0 and current_time.minute == 0):
            m = current_time.month - 1
            next_m_val = monthly_values[(m + 1) % 12]
            days_in_month = calendar.monthrange(current_time.year, current_time.month)[1]
            frac = (current_time.day - 1) / days_in_month
            current_val = monthly_values[m] * (1.0 - frac) + next_m_val * frac
        result[step] = current_val

    return result


def compute_dayfg(siminfo, steps):
    """Return array: 1 at first step and at midnight each day."""
    start = datetime.strptime(siminfo["start"], "%Y-%m-%d %H:%M:%S")
    result = np.zeros(steps, dtype=int)
    result[0] = 1
    for step in range(1, steps):
        t = start + timedelta(minutes=step * 60)
        if t.hour == 0 and t.minute == 0:
            result[step] = 1
    return result


# == Surface Routing ===========================================================

def proute(psur, RTOPFG, delt60, dec, src, surs):
    """Route potential surface detention to surface runoff."""
    if psur > 0.0002:
        if RTOPFG != 1:
            ssupr = (psur - surs) / delt60
            surse = dec * ssupr**0.6 if ssupr > 0.0 else 0.0
            sursnw = psur
            suro = 0.0
            for _ in range(100):
                if ssupr > 0.0:
                    ratio = sursnw / surse
                    fact = 1.0 + 0.6 * ratio**3 if ratio <= 1.0 else 1.6
                else:
                    ratio = 1.0e30
                    fact = 1.6
                ffact = (delt60 * src * fact**1.667) * (sursnw**1.667)
                fsuro = ffact - suro
                dfact = -1.667 * ffact
                dfsuro = dfact / sursnw - 1.0
                if ratio <= 1.0:
                    dfsuro += dfact / (fact * surse) * 1.8 * ratio**2
                dsuro = fsuro / dfsuro
                suro -= dsuro
                if suro <= 1.0e-10:
                    suro = 0.0
                sursnw = psur - suro
                if abs(suro) > 0.0 and abs(dsuro / suro) < 0.01:
                    break
            surs = sursnw
        else:
            ssupr = psur - surs
            sursm = (surs + psur) * 0.5
            if ssupr > 0.0:
                dummy = dec * ssupr**0.6
                if dummy > sursm:
                    surse = dummy
                    dummy = sursm * (1.0 + 0.6 * (sursm / surse)**3)
                else:
                    dummy = sursm * 1.6
            else:
                dummy = sursm * 1.6
            tsuro = delt60 * src * dummy**1.667
            suro = psur if tsuro > psur else tsuro
            surs = 0.0 if tsuro > psur else psur - suro
    else:
        suro = psur
        surs = 0.0

    if suro <= 1.0e-10:
        suro = 0.0
    return suro, surs


# == PWATER Simulation =========================================================

def run_pwater(siminfo, seg_params, input_ts):
    """Run PWATER simulation for one segment. Returns outputs and water balance info."""
    params = seg_params['parameters']
    states = seg_params['states']
    monthly = seg_params.get('monthly_cepsc')

    steps = len(input_ts)
    delt60 = 1.0

    CSNOFG = int(params.get('CSNOFG', 0))
    RTOPFG = int(params.get('RTOPFG', 1))
    UZFG = int(params.get('UZFG', 1))
    VCSFG = int(params.get('VCSFG', 0))
    VLEFG = int(params.get('VLEFG', 0))
    IFRDFG = int(params.get('IFRDFG', 0))

    agwetp = params.get('AGWETP', 0.0)
    basetp = params.get('BASETP', 0.0)
    infexp = params.get('INFEXP', 2.0)
    infild = params.get('INFILD', 2.0)
    lsur = params['LSUR']
    slsur = params['SLSUR']
    forest = params.get('FOREST', 0.0)

    ceps = states['CEPS']
    surs = states['SURS']
    uzs = states['UZS']
    ifws = states['IFWS']
    lzs = states['LZS']
    agws = states['AGWS']
    gwvs = states['GWVS']

    # Record initial storage for water balance
    init_storage = ceps + surs + uzs + ifws + lzs + agws

    if VCSFG and monthly:
        CEPSC = interpolate_monthly(siminfo, monthly, steps)
    else:
        CEPSC = np.full(steps, params.get('CEPSC', 0.01))

    INFILT_arr = np.full(steps, params['INFILT'] * delt60)
    LZSN_arr = np.full(steps, params['LZSN'])
    KVARY_arr = np.full(steps, params.get('KVARY', 0.0))
    DEEPFR_arr = np.full(steps, params.get('DEEPFR', 0.0))
    AGWRC_arr = np.full(steps, params['AGWRC'])
    INTFW_arr = np.full(steps, params.get('INTFW', 1.0))
    IRC_arr = np.full(steps, params.get('IRC', 0.5))
    NSUR_arr = np.full(steps, params.get('NSUR', 0.1))
    UZSN_arr = np.full(steps, params.get('UZSN', 0.5))
    LZETP_arr = np.full(steps, params.get('LZETP', 0.5))

    PREC = input_ts["PREC"].values
    PETINP = input_ts["PETINP"].values
    DAYFG = compute_dayfg(siminfo, steps)

    kgwV = 1.0 - AGWRC_arr**(delt60 / 24.0)

    SURO = np.zeros(steps)
    IFWO = np.zeros(steps)
    AGWO = np.zeros(steps)

    # Water balance accumulators
    total_et = 0.0
    total_deep = 0.0

    rlzrat = -1.0e30
    lzfrac = -1.0e30
    rparm = -1.0e30
    if agws < 0.0:
        agws = 0.0
    msupy = 0.0
    dec = float('nan')
    src = float('nan')
    kifw = float('nan')
    ifwk2 = float('nan')
    ifwk1 = float('nan')
    petadj = 1.0

    for step in range(steps):
        oldmsupy = msupy
        dayfg = int(DAYFG[step])
        kgw = kgwV[step]
        cepsc = CEPSC[step]
        uzsn = UZSN_arr[step]
        infilt = INFILT_arr[step]
        kvary = KVARY_arr[step]
        lzsn = LZSN_arr[step]
        lzetp = LZETP_arr[step]
        petinp = PETINP[step]

        supy = PREC[step]
        pet = petinp

        # Interception
        ceps = ceps + supy
        cepo = 0.0
        if ceps > cepsc:
            cepo = ceps - cepsc
            ceps = cepsc

        suri = cepo
        msupy = suri + surs
        lzrat = lzs / lzsn

        if msupy <= 0.0:
            surs = 0.0
            suro = 0.0
            ifwi = 0.0
            infil = 0.0
            uzi = 0.0
        else:
            ibar = infilt / (lzrat**infexp)
            imax = ibar * infild
            imin = ibar - (imax - ibar)

            if dayfg or oldmsupy == 0.0:
                dummy = NSUR_arr[step] * lsur
                dec = 0.00982 * (dummy / math.sqrt(slsur))**0.6
                src = 1020.0 * (math.sqrt(slsur) / dummy)

            ratio_intfw = max(1.0001, INTFW_arr[step] * 2.0**lzrat)

            if msupy <= imin:
                under = msupy
                over = 0.0
            elif msupy > imax:
                under = (imin + imax) * 0.5
                over = msupy - under
            else:
                over = ((msupy - imin)**2) * 0.5 / (imax - imin)
                under = msupy - over

            infil = under
            if over <= 0.0:
                surs = 0.0
                suro = 0.0
                ifwi = 0.0
                uzi = 0.0
            else:
                pdro = over
                if UZFG:
                    uzrat = uzs / uzsn
                    if uzrat < 2.0:
                        k1 = 3.0 - uzrat
                        uzfrac = 1.0 - (uzrat * 0.5) * ((1.0 / (1.0 + k1))**k1)
                    else:
                        k2 = (2.0 * uzrat) - 3.0
                        uzfrac = (1.0 / (1.0 + k2))**k2
                    uzi = pdro * uzfrac
                else:
                    uzi = 0.0
                    uzfrac = 0.0

                if uzi > pdro:
                    uzi = pdro
                uzfrac = uzi / pdro

                iimin = imin * ratio_intfw
                iimax = imax * ratio_intfw

                if msupy <= iimin:
                    over2 = 0.0
                elif msupy > iimax:
                    over2 = msupy - (iimin + iimax) * 0.5
                else:
                    over2 = ((msupy - iimin)**2) * 0.5 / (iimax - iimin)

                psur = over2
                pifwi = pdro - psur
                ifwi = pifwi * (1.0 - uzfrac)

                if psur <= 0.0:
                    surs = 0.0
                    suro = 0.0
                else:
                    psur = psur * (1.0 - uzfrac)
                    suro, surs = proute(psur, RTOPFG, delt60, dec, src, surs)

        # Interflow
        if dayfg:
            irc_val = IRC_arr[step]
            kifw = -math.log(irc_val) / (24.0 / delt60)
            ifwk2 = 1.0 - math.exp(-kifw)
            ifwk1 = 1.0 - (ifwk2 / kifw)

        inflo = ifwi
        value = inflo + ifws
        if value > 0.00002:
            ifwo = (ifwk1 * inflo) + (ifwk2 * ifws)
            ifws = value - ifwo
        else:
            ifwo = 0.0
            ifws = 0.0
            uzs = uzs + value

        # Upper zone
        uzrat_val = uzs / uzsn
        uzs = uzs + uzi
        perc = 0.0
        if uzrat_val - lzrat > 0.01:
            perc = 0.1 * infilt * uzsn * (uzrat_val - lzrat)**3
            if perc > uzs:
                perc = uzs
                uzs = 0.0
            else:
                uzs -= perc

        iperc = perc + infil

        # Lower zone
        lperc = iperc
        lzi = 0.0
        if lperc > 0.0:
            if abs(lzrat - rlzrat) > 0.02 or IFRDFG:
                rlzrat = lzrat
                if lzrat <= 1.0:
                    indx = 2.5 - 1.5 * lzrat
                    lzfrac = 1.0 - lzrat * (1.0 / (1.0 + indx))**indx
                else:
                    indx = 1.5 * lzrat - 0.5
                    lzfrac = (1.0 / (1.0 + indx))**indx
            lzi = lzfrac * lperc
            lzs += lzi

        # Groundwater
        gwi = iperc - lzi
        igwi = 0.0
        agwi = 0.0
        if gwi > 0.0:
            igwi = DEEPFR_arr[step] * gwi
            agwi = gwi - igwi
        ainflo = agwi
        agwo = 0.0

        if kvary > 0.0:
            gwvs += ainflo
            if dayfg:
                gwvs = gwvs * 0.97 if gwvs > 0.0001 else 0.0
            if agws > 1.0e-20:
                agwo = kgw * (1.0 + kvary * gwvs) * agws
                avail = ainflo + agws
                if agwo > avail:
                    agwo = avail
        elif agws > 1.0e-20:
            agwo = kgw * agws

        if agwo < 1.0e-12:
            agwo = 0.0

        agws = agws + (ainflo - agwo)
        if agws < 0.0:
            agws = 0.0

        # Evapotranspiration
        rempet = pet
        taet = 0.0
        baset = 0.0

        if rempet > 0.0 and basetp > 0.0:
            baspet = basetp * rempet
            if baspet > agwo:
                baset = agwo
                agwo = 0.0
            else:
                baset = baspet
                agwo -= baset
            taet += baset
            rempet -= baset

        cepe = 0.0
        if rempet > 0.0 and ceps > 0.0:
            if rempet > ceps:
                cepe = ceps
                ceps = 0.0
            else:
                cepe = rempet
                ceps -= cepe
            taet += cepe
            rempet -= cepe

        uzet = 0.0
        if rempet > 0.0:
            if uzs > 0.001:
                uzrat_et = uzs / uzsn
                uzpet = rempet if uzrat_et > 2.0 else 0.5 * uzrat_et * rempet
                if uzpet > uzs:
                    uzet = uzs
                    uzs = 0.0
                else:
                    uzet = uzpet
                    uzs -= uzet
            taet += uzet
            rempet -= uzet

        agwet = 0.0
        if rempet > 0.0 and agwetp > 0.0:
            gwpet = rempet * agwetp
            if gwpet > agws:
                agwet = agws
                agws = 0.0
            else:
                agwet = gwpet
                agws -= agwet
            if abs(kvary) > 0.0:
                gwvs -= agwet
            taet += agwet
            rempet -= agwet

        if dayfg:
            lzrat = lzs / lzsn
            rparm = 0.25 / (1.0 - lzetp) * lzrat * delt60 / 24.0 if lzetp <= 0.99999 else 1.0e10

        lzet = 0.0
        if rempet > 0.0 and lzs > 0.02:
            if lzetp >= 0.99999:
                lzpet = rempet * lzetp
            elif VLEFG <= 1:
                lzpet = 0.5 * rparm if rempet > rparm else rempet * (1.0 - rempet / (2.0 * rparm))
                if lzetp < 0.5:
                    lzpet = lzpet * 2.0 * lzetp
            else:
                lzpet = lzetp * lzrat * rempet if lzrat < 1.0 else lzetp * rempet
            lzet = lzpet if lzpet < (lzs - 0.02) else lzs - 0.02
            lzs -= lzet
            taet += lzet
            rempet -= lzet

        SURO[step] = suro
        IFWO[step] = ifwo
        AGWO[step] = agwo

        # Accumulate water balance quantities
        total_et += taet
        total_deep += igwi

    # Final storage (excluding gwvs which is not physical storage)
    final_storage = ceps + surs + uzs + ifws + lzs + agws

    return {
        "SURO": SURO,
        "IFWO": IFWO,
        "AGWO": AGWO,
        "total_et": total_et,
        "total_deep": total_deep,
        "init_storage": init_storage,
        "final_storage": final_storage,
    }


# == HDF5 Output ==============================================================

def write_hdf5(filepath, siminfo, segments, results, agg_suro, agg_ifwo, agg_agwo):
    """Write all simulation data to HDF5 file."""
    with h5py.File(filepath, "w") as f:
        # Metadata group with attributes
        meta = f.create_group("metadata")
        meta.attrs["start_date"] = siminfo["start"]
        meta.attrs["end_date"] = siminfo["stop"]
        meta.attrs["units"] = siminfo["units"]
        meta.attrs["num_segments"] = len(segments)

        # Segments group
        segs_grp = f.create_group("segments")
        for seg_id in sorted(segments.keys()):
            seg = segments[seg_id]
            seg_grp = segs_grp.create_group(seg_id)

            # Parameters as scalar datasets
            params_grp = seg_grp.create_group("parameters")
            for pname, pval in seg['parameters'].items():
                params_grp.create_dataset(pname, data=np.float64(pval))

            # Initial states as scalar datasets
            states_grp = seg_grp.create_group("states")
            for sname, sval in seg['states'].items():
                states_grp.create_dataset(sname, data=np.float64(sval))

            # Hourly output datasets
            hourly_grp = seg_grp.create_group("hourly")
            res = results[seg_id]
            hourly_grp.create_dataset("SURO", data=res["SURO"].astype(np.float64))
            hourly_grp.create_dataset("IFWO", data=res["IFWO"].astype(np.float64))
            hourly_grp.create_dataset("AGWO", data=res["AGWO"].astype(np.float64))

        # Aggregate group
        agg_grp = f.create_group("aggregate")
        agg_grp.create_dataset("SURO", data=agg_suro.astype(np.float64))
        agg_grp.create_dataset("IFWO", data=agg_ifwo.astype(np.float64))
        agg_grp.create_dataset("AGWO", data=agg_agwo.astype(np.float64))


# == SQLite Output =============================================================

def write_sqlite(filepath, segments, results, input_ts):
    """Write parameter, hourly output, and water balance tables to SQLite."""
    total_precip = float(input_ts["PREC"].sum())

    conn = sqlite3.connect(filepath)

    # Create tables
    conn.execute("""CREATE TABLE segments (
        segment_id TEXT PRIMARY KEY,
        forest REAL,
        lzsn REAL,
        infilt REAL,
        agwrc REAL,
        kvary REAL
    )""")

    conn.execute("""CREATE TABLE hourly_output (
        segment_id TEXT,
        hour INTEGER,
        suro REAL,
        ifwo REAL,
        agwo REAL
    )""")

    conn.execute("""CREATE TABLE water_balance (
        segment_id TEXT PRIMARY KEY,
        total_precip REAL,
        total_et REAL,
        total_suro REAL,
        total_ifwo REAL,
        total_agwo REAL,
        total_deep REAL,
        balance_error REAL
    )""")

    # Insert segment parameters
    for seg_id in sorted(segments.keys()):
        p = segments[seg_id]['parameters']
        conn.execute(
            "INSERT INTO segments VALUES (?, ?, ?, ?, ?, ?)",
            (seg_id,
             float(p.get('FOREST', 0.0)),
             float(p.get('LZSN', 0.0)),
             float(p.get('INFILT', 0.0)),
             float(p.get('AGWRC', 0.0)),
             float(p.get('KVARY', 0.0)))
        )

    # Insert hourly output rows
    hourly_rows = []
    for seg_id in sorted(segments.keys()):
        res = results[seg_id]
        suro = res["SURO"]
        ifwo = res["IFWO"]
        agwo = res["AGWO"]
        for h in range(len(suro)):
            hourly_rows.append((seg_id, h, float(suro[h]), float(ifwo[h]), float(agwo[h])))
    conn.executemany("INSERT INTO hourly_output VALUES (?, ?, ?, ?, ?)", hourly_rows)

    # Insert water balance rows
    for seg_id in sorted(segments.keys()):
        res = results[seg_id]
        t_suro = float(res["SURO"].sum())
        t_ifwo = float(res["IFWO"].sum())
        t_agwo = float(res["AGWO"].sum())
        t_et = res["total_et"]
        t_deep = res["total_deep"]
        delta_storage = res["final_storage"] - res["init_storage"]
        balance_error = abs(total_precip - (t_et + t_suro + t_ifwo + t_agwo + t_deep + delta_storage))

        conn.execute(
            "INSERT INTO water_balance VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (seg_id, total_precip, t_et, t_suro, t_ifwo, t_agwo, t_deep, balance_error)
        )

    conn.commit()
    conn.close()


# == Main ======================================================================

def main():
    # Parse UCI
    siminfo, segments = parse_uci("/app/watershed.uci")
    print(f"Parsed {len(segments)} segments: {list(segments.keys())}")

    # Write parsed config JSON
    parsed_out = {}
    for seg_id, seg in segments.items():
        entry = {
            "parameters": seg['parameters'],
            "states": seg['states'],
        }
        if seg.get('monthly_cepsc'):
            entry["monthly_cepsc"] = seg['monthly_cepsc']
        parsed_out[seg_id] = entry
    with open("/app/parsed_config.json", "w") as f:
        json.dump(parsed_out, f, indent=2)
    print("Wrote parsed_config.json")

    # Load inputs
    input_ts = pd.read_csv("/app/input_timeseries.csv")
    with open("/app/area_weights.json") as f:
        area_weights = json.load(f)

    # Run simulation for each segment
    results = {}
    for seg_id in sorted(segments.keys()):
        seg = segments[seg_id]
        res = run_pwater(siminfo, seg, input_ts)
        results[seg_id] = res

        # Write per-segment CSV
        df = pd.DataFrame({"SURO": res["SURO"], "IFWO": res["IFWO"], "AGWO": res["AGWO"]})
        outpath = f"/app/output_{seg_id}.csv"
        df.to_csv(outpath, index=False, float_format='%.10e')
        print(f"{seg_id}: SURO={res['SURO'].sum():.6f} IFWO={res['IFWO'].sum():.6f} AGWO={res['AGWO'].sum():.6f}")
        print(f"  ET={res['total_et']:.6f} DEEP={res['total_deep']:.6f} "
              f"dStorage={res['final_storage'] - res['init_storage']:.6f}")

    # Compute area-weighted aggregate
    steps = len(input_ts)
    agg_suro = np.zeros(steps)
    agg_ifwo = np.zeros(steps)
    agg_agwo = np.zeros(steps)

    for seg_id, res in results.items():
        w = area_weights[seg_id]
        agg_suro += w * res["SURO"]
        agg_ifwo += w * res["IFWO"]
        agg_agwo += w * res["AGWO"]

    # Write aggregate CSV
    agg_df = pd.DataFrame({"SURO": agg_suro, "IFWO": agg_ifwo, "AGWO": agg_agwo})
    agg_df.to_csv("/app/output.csv", index=False, float_format='%.10e')
    print(f"AGG: SURO={agg_suro.sum():.6f} IFWO={agg_ifwo.sum():.6f} AGWO={agg_agwo.sum():.6f}")

    # Write HDF5 archive
    write_hdf5("/app/results.h5", siminfo, segments, results, agg_suro, agg_ifwo, agg_agwo)
    print("Wrote results.h5")

    # Write SQLite database
    write_sqlite("/app/watershed.db", segments, results, input_ts)
    print("Wrote watershed.db")


if __name__ == "__main__":
    main()
