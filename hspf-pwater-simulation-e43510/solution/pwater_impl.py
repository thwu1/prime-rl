#!/usr/bin/env python3

"""HSPF PWATER simulation — parses UCI config, runs pervious-land water budget,
writes results to HDF5."""

import csv
import math
import re
from datetime import datetime, timedelta


def parse_uci(path):
    """Parse HSPF UCI file to extract PWATER configuration."""
    params = {}
    state = {}
    monthly_cepsc = {}
    siminfo = {'start': '2018-01-01 00:00:00', 'delt': 60, 'units': 1}

    with open(path) as f:
        lines = f.readlines()

    def is_skip(line):
        s = line.strip()
        return not s or '***' in s or s.startswith('<') or s.startswith('#')

    section = None
    subsection = None

    for line in lines:
        stripped = line.strip()

        # Track END markers
        if stripped.startswith('END '):
            end_name = ' '.join(stripped.split()[1:])
            if subsection and end_name == subsection:
                subsection = None
            elif section and end_name == section:
                section = None
                subsection = None
            continue

        # Track top-level sections
        if stripped in ('GLOBAL', 'OPN SEQUENCE', 'PERLND', 'IMPLND', 'RCHRES'):
            section = stripped
            subsection = None
            continue

        # Parse GLOBAL
        if section == 'GLOBAL':
            if 'START' in stripped:
                m = re.search(r'START\s+(\d{4})', stripped)
                if m:
                    siminfo['start'] = f"{m.group(1)}-01-01 00:00:00"
            if 'UNIT SYSTEM' in stripped:
                m = re.search(r'UNIT SYSTEM\s+(\d+)', stripped)
                if m:
                    siminfo['units'] = int(m.group(1))
            continue

        # Parse OPN SEQUENCE for timestep
        if section == 'OPN SEQUENCE':
            if 'INDELT' in stripped:
                m = re.search(r'INDELT\s+(\d+):(\d+)', stripped)
                if m:
                    siminfo['delt'] = int(m.group(1)) * 60 + int(m.group(2))
            continue

        # Parse PERLND subsections
        if section == 'PERLND':
            # Detect subsection boundaries
            known_subs = (
                'PWAT-PARM1', 'PWAT-PARM2', 'PWAT-PARM3', 'PWAT-PARM4',
                'MON-INTERCEP', 'PWAT-STATE1',
                'ACTIVITY', 'GEN-INFO', 'PSTEMP-PARM2', 'PWT-PARM2',
                'PRINT-INFO',
            )
            if stripped in known_subs:
                subsection = stripped
                continue

            if subsection and not is_skip(line):
                vals = stripped.split()
                if not vals:
                    continue
                try:
                    int(vals[0])  # segment ID
                except ValueError:
                    continue

                if subsection == 'PWAT-PARM1' and len(vals) >= 10:
                    names = ['CSNOFG', 'RTOPFG', 'UZFG', 'VCSFG', 'VUZFG',
                             'VNNFG', 'VIFWFG', 'VIRCFG', 'VLEFG']
                    for j, name in enumerate(names):
                        params[name] = int(vals[j + 1])

                elif subsection == 'PWAT-PARM2' and len(vals) >= 8:
                    names = ['FOREST', 'LZSN', 'INFILT', 'LSUR', 'SLSUR', 'KVARY', 'AGWRC']
                    for j, name in enumerate(names):
                        params[name] = float(vals[j + 1])

                elif subsection == 'PWAT-PARM3' and len(vals) >= 8:
                    names = ['PETMAX', 'PETMIN', 'INFEXP', 'INFILD', 'DEEPFR', 'BASETP', 'AGWETP']
                    for j, name in enumerate(names):
                        params[name] = float(vals[j + 1])

                elif subsection == 'PWAT-PARM4' and len(vals) >= 7:
                    names = ['CEPSC', 'UZSN', 'NSUR', 'INTFW', 'IRC', 'LZETP']
                    for j, name in enumerate(names):
                        params[name] = float(vals[j + 1])

                elif subsection == 'PWAT-STATE1' and len(vals) >= 8:
                    names = ['CEPS', 'SURS', 'UZS', 'IFWS', 'LZS', 'AGWS', 'GWVS']
                    for j, name in enumerate(names):
                        state[name] = float(vals[j + 1])

                elif subsection == 'MON-INTERCEP' and len(vals) >= 13:
                    months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                              'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
                    for j, month in enumerate(months):
                        monthly_cepsc[month] = float(vals[j + 1])

    return {
        'parameters': params,
        'initial_conditions': state,
        'siminfo': siminfo,
        'monthly_cepsc': monthly_cepsc,
    }


def load_forcing(path):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((float(row['PREC']), float(row['PETINP'])))
    return rows


def proute(psur, rtopfg, delt60, dec, src, surs):
    """Route overland flow using ARM/NPS or Newton's method."""
    if psur > 0.0002:
        if rtopfg != 1:
            ssupr = (psur - surs) / delt60
            surse = dec * ssupr ** 0.6 if ssupr > 0.0 else 0.0
            sursnw = psur
            suro = 0.0
            for _ in range(100):
                if ssupr > 0.0:
                    ratio = sursnw / surse
                    fact = 1.0 + 0.6 * ratio ** 3 if ratio <= 1.0 else 1.6
                else:
                    ratio = 1.0e30
                    fact = 1.6
                ffact = (delt60 * src * fact ** 1.667) * (sursnw ** 1.667)
                fsuro = ffact - suro
                dfact = -1.667 * ffact
                dfsuro = dfact / sursnw - 1.0
                if ratio <= 1.0:
                    dfsuro += dfact / (fact * surse) * 1.8 * ratio ** 2
                dsuro = fsuro / dfsuro
                suro = suro - dsuro
                if suro <= 1.0e-10:
                    suro = 0.0
                sursnw = psur - suro
                if abs(suro) > 0.0:
                    if abs(dsuro / suro) < 0.01:
                        break
            surs = sursnw
        else:
            ssupr = psur - surs
            sursm = (surs + psur) * 0.5
            if ssupr > 0.0:
                dummy = dec * ssupr ** 0.6
                if dummy > sursm:
                    surse = dummy
                    dummy = sursm * (1.0 + 0.6 * (sursm / surse) ** 3)
                else:
                    dummy = sursm * 1.6
            else:
                dummy = sursm * 1.6
            tsuro = delt60 * src * dummy ** 1.667
            if tsuro > psur:
                suro = psur
                surs = 0.0
            else:
                suro = tsuro
                surs = psur - suro
    else:
        suro = psur
        surs = 0.0

    if suro <= 1.0e-10:
        suro = 0.0
    return suro, surs


def build_monthly_cepsc(monthly_vals, start_dt, steps, delt):
    """Build per-step CEPSC array from monthly values via interpolation."""
    months_order = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                    'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
    mvals = [monthly_vals[m] for m in months_order]
    cepsc = []
    for s in range(steps):
        t = start_dt + timedelta(minutes=s * delt)
        m = t.month - 1
        day_frac = t.day / 30.0
        next_m = (m + 1) % 12
        cepsc.append(mvals[m] * (1 - day_frac) + mvals[next_m] * day_frac)
    return cepsc


def run_pwater(config, forcing):
    """Run the PWATER simulation, returning flows, states, and balance info."""
    p = config['parameters']
    ic = config['initial_conditions']
    si = config['siminfo']

    steps = len(forcing)
    delt = si['delt']
    delt60 = delt / 60.0

    RTOPFG = int(p.get('RTOPFG', 1))
    UZFG = int(p.get('UZFG', 1))
    VLEFG = int(p.get('VLEFG', 0))
    IFRDFG = int(p.get('IFRDFG', 0))
    VCSFG = int(p.get('VCSFG', 0))

    forest = p.get('FOREST', 0.0)
    lzsn = p['LZSN']
    infilt_p = p['INFILT'] * delt60
    lsur = p['LSUR']
    slsur = p['SLSUR']
    kvary = p['KVARY']
    agwrc = p['AGWRC']
    infexp = p['INFEXP']
    infild = p['INFILD']
    deepfr = p['DEEPFR']
    basetp = p['BASETP']
    agwetp = p['AGWETP']
    uzsn = p['UZSN']
    nsur = p['NSUR']
    intfw = p['INTFW']
    irc = p['IRC']
    lzetp = p['LZETP']

    start_dt = datetime.strptime(si['start'], "%Y-%m-%d %H:%M:%S")
    if VCSFG == 1 and config.get('monthly_cepsc'):
        CEPSC = build_monthly_cepsc(config['monthly_cepsc'], start_dt, steps, delt)
    else:
        CEPSC = [p.get('CEPSC', 0.01)] * steps

    kgw = 1.0 - agwrc ** (delt60 / 24.0)

    DAYFG = [0] * steps
    DAYFG[0] = 1
    for s in range(1, steps):
        t = start_dt + timedelta(minutes=s * delt)
        if t.hour == 0 and t.minute == 0:
            DAYFG[s] = 1

    ceps = ic['CEPS']
    surs = ic['SURS']
    uzs = ic['UZS']
    ifws = ic['IFWS']
    lzs = ic['LZS']
    agws = ic['AGWS']
    gwvs = ic['GWVS']

    # Initial storage (excluding GWVS which is a slope index, not water volume)
    initial_storage = ceps + surs + uzs + ifws + lzs + agws

    SURO = []
    IFWO = []
    AGWO = []
    UZS_arr = []
    LZS_arr = []
    AGWS_arr = []

    cum_et = 0.0
    cum_deep = 0.0
    total_precip = 0.0

    msupy = 0.0
    dec = 0.0
    src = 0.0
    kifw = 0.0
    ifwk2 = 0.0
    ifwk1 = 0.0
    rlzrat = -1.0e30
    lzfrac = -1.0e30
    rparm = -1.0e30
    inffac = 1.0

    for step in range(steps):
        oldmsupy = msupy
        dayfg = DAYFG[step]
        cepsc = CEPSC[step]
        prec, petinp = forcing[step]

        total_precip += prec

        supy = prec
        pet = petinp

        # interception
        ceps = ceps + supy
        cepo = 0.0
        if ceps > cepsc:
            cepo = ceps - cepsc
            ceps = cepsc

        suri = cepo
        msupy = suri + surs
        lzrat = lzs / lzsn

        suro = 0.0
        ifwi = 0.0
        infil = 0.0
        uzi = 0.0

        if msupy > 0.0:
            ibar = infilt_p / (lzrat ** infexp)
            if inffac < 1.0:
                ibar = ibar * inffac
            imax = ibar * infild
            imin = ibar - (imax - ibar)

            if dayfg or oldmsupy == 0.0:
                dummy = nsur * lsur
                dec = 0.00982 * (dummy / math.sqrt(slsur)) ** 0.6
                src = 1020.0 * (math.sqrt(slsur) / dummy)

            ratio = max(1.0001, intfw * 2.0 ** lzrat)

            if msupy <= imin:
                under = msupy
                over = 0.0
            elif msupy > imax:
                under = (imin + imax) * 0.5
                over = msupy - under
            else:
                over = ((msupy - imin) ** 2) * 0.5 / (imax - imin)
                under = msupy - over

            infil = under

            if over > 0.0:
                pdro = over

                if UZFG:
                    uzrat_v = uzs / uzsn
                    if uzrat_v < 2.0:
                        k1 = 3.0 - uzrat_v
                        uzfrac = 1.0 - (uzrat_v * 0.5) * ((1.0 / (1.0 + k1)) ** k1)
                    else:
                        k2 = (2.0 * uzrat_v) - 3.0
                        uzfrac = (1.0 / (1.0 + k2)) ** k2
                    uzi = pdro * uzfrac
                else:
                    uzra = [0.0, 1.25, 1.50, 1.75, 2.00, 2.10, 2.20, 2.25, 2.5, 4.0]
                    intgrl = [0.0, 1.29, 1.58, 1.92, 2.36, 2.81, 3.41, 3.8, 7.1, 3478.0]
                    uzraa = uzs / uzsn
                    kk = 8
                    for ii in range(len(uzra) - 1):
                        if uzraa < uzra[ii + 1]:
                            kk = ii
                            break
                    intga = intgrl[kk] + (intgrl[kk + 1] - intgrl[kk]) * (uzraa - uzra[kk]) / (uzra[kk + 1] - uzra[kk])
                    intgb = (pdro / uzsn) + intga
                    kk2 = 8
                    for ii in range(len(intgrl) - 1):
                        if intgb < intgrl[ii + 1]:
                            kk2 = ii
                            break
                    uzrab = uzra[kk2] + (uzra[kk2 + 1] - uzra[kk2]) * (intgb - intgrl[kk2]) / (intgrl[kk2 + 1] - intgrl[kk2])
                    uzi = (uzrab - uzraa) * uzsn
                    uzi = max(0.0, uzi)

                if uzi > pdro:
                    uzi = pdro
                uzfrac_v = uzi / pdro

                iimin = imin * ratio
                iimax = imax * ratio
                if msupy <= iimin:
                    over2 = 0.0
                elif msupy > iimax:
                    over2 = msupy - (iimin + iimax) * 0.5
                else:
                    over2 = ((msupy - iimin) ** 2) * 0.5 / (iimax - iimin)

                psur = over2
                pifwi = pdro - psur
                ifwi = pifwi * (1.0 - uzfrac_v)

                if psur > 0.0:
                    psur = psur * (1.0 - uzfrac_v)
                    suro, surs = proute(psur, RTOPFG, delt60, dec, src, surs)
                else:
                    surs = 0.0
                    suro = 0.0
            else:
                surs = 0.0
                suro = 0.0

        # interflow routing
        if dayfg:
            kifw = -math.log(irc) / (24.0 / delt60)
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

        # upper zone / percolation
        uzrat_v = uzs / uzsn
        uzs = uzs + uzi
        perc = 0.0
        if uzrat_v - lzrat > 0.01:
            perc = 0.1 * infilt_p * inffac * uzsn * (uzrat_v - lzrat) ** 3
            if perc > uzs:
                perc = uzs
                uzs = 0.0
            else:
                uzs -= perc

        iperc = perc + infil

        # lower zone
        lperc = iperc
        lzi = 0.0
        if lperc > 0.0:
            if abs(lzrat - rlzrat) > 0.02 or IFRDFG:
                rlzrat = lzrat
                if lzrat <= 1.0:
                    indx = 2.5 - 1.5 * lzrat
                    lzfrac = 1.0 - lzrat * (1.0 / (1.0 + indx)) ** indx
                else:
                    indx = 1.5 * lzrat - 0.5
                    lzfrac = (1.0 / (1.0 + indx)) ** indx
            lzi = lzfrac * lperc
            lzs += lzi

        # groundwater
        gwi = iperc - lzi
        igwi = deepfr * gwi if gwi > 0.0 else 0.0
        agwi = gwi - igwi if gwi > 0.0 else 0.0
        ainflo = agwi
        agwo = 0.0

        cum_deep += igwi

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

        # evapotranspiration
        rempet = pet
        taet = 0.0

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
                ur = uzs / uzsn
                uzpet = rempet if ur > 2.0 else 0.5 * ur * rempet
                if uzpet > uzs:
                    uzet = uzs
                    uzs = 0.0
                else:
                    uzet = uzpet
                    uzs -= uzet
            taet += uzet
            rempet -= uzet

        if rempet > 0.0 and agwetp > 0.0:
            gwpet = rempet * agwetp
            if gwpet > agws:
                agwet = agws
                agws = 0.0
            else:
                agwet = gwpet
                agws -= agwet
            taet += agwet
            rempet -= agwet

        if dayfg:
            lr2 = lzs / lzsn
            if lzetp <= 0.99999:
                rparm = 0.25 / (1.0 - lzetp) * lr2 * delt60 / 24.0
            else:
                rparm = 1.0e10
        if rempet > 0.0 and lzs > 0.02:
            if lzetp >= 0.99999:
                lzpet = rempet * lzetp
            elif VLEFG <= 1:
                if rempet > rparm:
                    lzpet = 0.5 * rparm
                else:
                    lzpet = rempet * (1.0 - rempet / (2.0 * rparm))
                if lzetp < 0.5:
                    lzpet = lzpet * 2.0 * lzetp
            else:
                lr2b = lzs / lzsn
                if lr2b < 1.0:
                    lzpet = lzetp * lr2b * rempet
                else:
                    lzpet = lzetp * rempet
            lzet = lzpet if lzpet < (lzs - 0.02) else lzs - 0.02
            lzs -= lzet
            taet += lzet
            rempet -= lzet

        cum_et += taet

        # Record state and output
        UZS_arr.append(uzs)
        LZS_arr.append(lzs)
        AGWS_arr.append(agws)
        SURO.append(suro)
        IFWO.append(ifwo)
        AGWO.append(agwo)

    final_storage = ceps + surs + uzs + ifws + lzs + agws

    return {
        'SURO': SURO, 'IFWO': IFWO, 'AGWO': AGWO,
        'UZS': UZS_arr, 'LZS': LZS_arr, 'AGWS': AGWS_arr,
        'total_precip': total_precip,
        'total_et': cum_et,
        'total_deep': cum_deep,
        'initial_storage': initial_storage,
        'final_storage': final_storage,
    }


def main():
    import h5py

    config = parse_uci('/app/watershed.uci')
    forcing = load_forcing('/app/forcing.csv')

    result = run_pwater(config, forcing)

    suro = result['SURO']
    ifwo = result['IFWO']
    agwo = result['AGWO']
    pero = [s + i + a for s, i, a in zip(suro, ifwo, agwo)]
    n = len(suro)

    total_outflow = sum(pero)
    delta_storage = result['final_storage'] - result['initial_storage']
    water_balance_error = abs(
        result['total_precip'] - total_outflow - result['total_et']
        - result['total_deep'] - delta_storage
    )

    with h5py.File('/app/output.h5', 'w') as f:
        # Root attributes
        f.attrs['model'] = 'HSP2-PWATER'
        f.attrs['segment_id'] = 'P101'

        # Flow datasets with gzip compression
        pw = f.create_group('PERLND/P101/PWATER')
        for name, data in [('SURO', suro), ('IFWO', ifwo),
                           ('AGWO', agwo), ('PERO', pero)]:
            pw.create_dataset(name, data=data, dtype='float64',
                              compression='gzip', compression_opts=1)

        # State datasets with gzip compression
        st = f.create_group('PERLND/P101/STATE')
        for name, key in [('UZS', 'UZS'), ('LZS', 'LZS'), ('AGWS', 'AGWS')]:
            st.create_dataset(name, data=result[key], dtype='float64',
                              compression='gzip', compression_opts=1)

        # Summary attributes
        sg = f.create_group('SUMMARY')
        sg.attrs['total_precip'] = result['total_precip']
        sg.attrs['total_outflow'] = total_outflow
        sg.attrs['total_et'] = result['total_et']
        sg.attrs['water_balance_error'] = water_balance_error
        sg.attrs['simulation_hours'] = n


if __name__ == '__main__':
    main()
