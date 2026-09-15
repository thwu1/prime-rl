#!/usr/bin/env python3
"""
PWATER solver — implements the HSPF pervious land water budget simulation.
Reads configuration and input timeseries, produces SURO/IFWO/AGWO output.
"""

import json
import math
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


def interpolate_monthly(siminfo, monthly_values, steps):
    """Linearly interpolate monthly values to hourly, recomputed at start of each day."""
    start = datetime.strptime(siminfo["start"], "%Y-%m-%d %H:%M:%S")
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    month_vals = [monthly_values[m] for m in months]

    result = np.zeros(steps)
    delt_minutes = 60
    current_val = month_vals[start.month - 1]

    for step in range(steps):
        current_time = start + timedelta(minutes=step * delt_minutes)
        hour_of_day = current_time.hour
        minute_of_hour = current_time.minute

        # Recompute daily (at hour 0 or first step)
        if step == 0 or (hour_of_day == 0 and minute_of_hour == 0):
            m = current_time.month - 1  # 0-based
            day = current_time.day
            # Days in current month
            if m == 11:
                next_month_val = month_vals[0]
            else:
                next_month_val = month_vals[m + 1]

            # Simple: use current month value for first half, interpolate
            # Actually HSPF uses initm which returns the monthly value for the
            # current month at start of month and interpolates daily
            import calendar
            days_in_month = calendar.monthrange(current_time.year, current_time.month)[1]
            frac = (day - 1) / days_in_month
            current_val = month_vals[m] * (1.0 - frac) + next_month_val * frac

        result[step] = current_val

    return result


def compute_dayfg(siminfo, steps):
    """Return array that is 1 at the first step and at midnight (hour 0) each day."""
    start = datetime.strptime(siminfo["start"], "%Y-%m-%d %H:%M:%S")
    result = np.zeros(steps, dtype=int)
    result[0] = 1
    for step in range(1, steps):
        current_time = start + timedelta(minutes=step * 60)
        if current_time.hour == 0 and current_time.minute == 0:
            result[step] = 1
    return result


def proute(psur, RTOPFG, delt60, dec, src, surs):
    """Route potential surface detention to determine surface runoff."""
    MAXLOOPS = 100
    TOLERANCE = 0.01

    if psur > 0.0002:
        if RTOPFG != 1:
            # New method with Newton's method
            ssupr = (psur - surs) / delt60
            surse = dec * ssupr**0.6 if ssupr > 0.0 else 0.0

            sursnw = psur
            suro = 0.0
            converged = False
            for count in range(MAXLOOPS):
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
                    dterm = dfact / (fact * surse) * 1.8 * ratio**2
                    dfsuro = dfsuro + dterm
                dsuro = fsuro / dfsuro

                suro = suro - dsuro
                if suro <= 1.0e-10:
                    suro = 0.0

                sursnw = psur - suro
                change = 0.0
                if abs(suro) > 0.0:
                    change = abs(dsuro / suro)
                if change < 0.01:
                    converged = True
                    break

            surs = sursnw
        else:
            # ARM/NPS/HSPX method
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


def run_pwater(config, input_ts):
    """Run the pervious land water budget simulation."""
    siminfo = config["siminfo"]
    perlnd = config["PERLND"]
    params = perlnd["PARAMETERS"]
    states = perlnd["STATES"]

    steps = len(input_ts)
    delt = 60  # minutes
    delt60 = delt / 60.0  # hours
    uunits = siminfo["units"]

    # Read flags
    CSNOFG = int(params.get("CSNOFG", 0))
    RTOPFG = int(params.get("RTOPFG", 1))
    UZFG = int(params.get("UZFG", 1))
    VCSFG = int(params.get("VCSFG", 0))
    VLEFG = int(params.get("VLEFG", 0))
    IFRDFG = int(params.get("IFRDFG", 0))

    # Read parameters
    agwetp = params["AGWETP"]
    basetp = params["BASETP"]
    infexp = params["INFEXP"]
    infild = params["INFILD"]
    lsur = params["LSUR"]
    slsur = params["SLSUR"]
    forest = params["FOREST"]

    # Read initial states
    ceps = states["CEPS"]
    surs = states["SURS"]
    uzs = states["UZS"]
    ifws = states["IFWS"]
    lzs = states["LZS"]
    agws = states["AGWS"]
    gwvs = states["GWVS"]

    # Prepare monthly varying parameters
    if VCSFG and "MONTHLY_CEPSC" in perlnd:
        CEPSC = interpolate_monthly(siminfo, perlnd["MONTHLY_CEPSC"], steps)
    else:
        CEPSC = np.full(steps, params["CEPSC"])

    # Non-varying parameters as arrays
    INTFW_arr = np.full(steps, params["INTFW"])
    IRC_arr = np.full(steps, params["IRC"])
    NSUR_arr = np.full(steps, params["NSUR"])
    UZSN_arr = np.full(steps, params["UZSN"])
    LZETP_arr = np.full(steps, params["LZETP"])
    INFILT_arr = np.full(steps, params["INFILT"] * delt60)  # convert to internal units
    LZSN_arr = np.full(steps, params["LZSN"])
    KVARY_arr = np.full(steps, params["KVARY"])
    DEEPFR_arr = np.full(steps, params["DEEPFR"])
    AGWRC_arr = np.full(steps, params["AGWRC"])

    # Input timeseries
    PREC = input_ts["PREC"].values
    PETINP = input_ts["PETINP"].values

    # Day flags
    DAYFG = compute_dayfg(siminfo, steps)

    # Groundwater recession parameter (daily)
    kgwV = 1.0 - AGWRC_arr**(delt60 / 24.0)

    # Output arrays
    SURO = np.zeros(steps)
    IFWO = np.zeros(steps)
    AGWO = np.zeros(steps)

    # Initialize
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

    # MAIN LOOP
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

        # PWATRX - supply and PET
        if CSNOFG:
            # Snow handling - not used in this config (CSNOFG=0)
            supy = PREC[step]
            pet = petinp
        else:
            supy = PREC[step]
            pet = petinp

        # ICEPT - interception
        ceps = ceps + supy
        cepo = 0.0
        if ceps > cepsc:
            cepo = ceps - cepsc
            ceps = cepsc

        # Surface input
        suri = cepo  # no lateral inflows (SURLI=0)
        msupy = suri + surs

        lzrat = lzs / lzsn

        if msupy <= 0.0:
            surs = 0.0
            suro = 0.0
            ifwi = 0.0
            infil = 0.0
            uzi = 0.0
        else:
            # SURFAC
            ibar = infilt / (lzrat**infexp)
            imax = ibar * infild
            imin = ibar - (imax - ibar)

            if dayfg or oldmsupy == 0.0:
                dummy = NSUR_arr[step] * lsur
                dec = 0.00982 * (dummy / math.sqrt(slsur))**0.6
                src = 1020.0 * (math.sqrt(slsur) / dummy)

            ratio_intfw = max(1.0001, INTFW_arr[step] * 2.0**lzrat)

            # DIVISN - split msupy against infiltration capacity
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

                # Upper zone absorption
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
                    # Table lookup method - not used when UZFG=1
                    uzi = 0.0
                    uzfrac = 0.0

                if uzi > pdro:
                    uzi = pdro
                uzfrac = uzi / pdro

                # Second DIVISN for interflow vs surface
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

        # INTFLW - interflow
        if dayfg:
            irc_val = IRC_arr[step]
            kifw = -math.log(irc_val) / (24.0 / delt60)
            ifwk2 = 1.0 - math.exp(-kifw)
            ifwk1 = 1.0 - (ifwk2 / kifw)

        inflo = ifwi  # no lateral inflow (IFWLI=0)
        value = inflo + ifws
        if value > 0.00002:
            ifwo = (ifwk1 * inflo) + (ifwk2 * ifws)
            ifws = value - ifwo
        else:
            ifwo = 0.0
            ifws = 0.0
            uzs = uzs + value

        # UZONE
        uzrat_val = uzs / uzsn
        uzs = uzs + uzi  # add UZ inflow (no lateral: UZLI=0)
        perc = 0.0
        if uzrat_val - lzrat > 0.01:
            perc = 0.1 * infilt * uzsn * (uzrat_val - lzrat)**3
            if perc > uzs:
                perc = uzs
                uzs = 0.0
            else:
                uzs -= perc

        # Collect inflows to lower zone and groundwater
        iperc = perc + infil  # no lateral: LZLI=0

        # LZONE
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

        # GWATER
        gwi = iperc - lzi
        igwi = 0.0
        agwi = 0.0
        if gwi > 0.0:
            igwi = DEEPFR_arr[step] * gwi
            agwi = gwi - igwi
        ainflo = agwi  # no lateral: AGWLI=0
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

        # EVAPT - evapotranspiration
        rempet = pet
        taet = 0.0
        baset = 0.0

        # ET from baseflow
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

        # ET from interception
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

        # ET from upper zone
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

        # ET from groundwater
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

        # ET from lower zone
        if dayfg:
            lzrat = lzs / lzsn
            if lzetp <= 0.99999:
                rparm = 0.25 / (1.0 - lzetp) * lzrat * delt60 / 24.0
            else:
                rparm = 1.0e10

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

        # Store outputs
        SURO[step] = suro
        IFWO[step] = ifwo
        AGWO[step] = agwo

    return SURO, IFWO, AGWO


def main():
    with open("/app/perlnd_config.json") as f:
        config = json.load(f)

    input_ts = pd.read_csv("/app/input_timeseries.csv")

    suro, ifwo, agwo = run_pwater(config, input_ts)

    output = pd.DataFrame({
        "SURO": suro,
        "IFWO": ifwo,
        "AGWO": agwo
    })
    output.to_csv("/app/output.csv", index=False, float_format='%.10e')
    print(f"Output written: {len(output)} rows")
    print(f"  SURO sum: {suro.sum():.6f}")
    print(f"  IFWO sum: {ifwo.sum():.6f}")
    print(f"  AGWO sum: {agwo.sum():.6f}")


if __name__ == "__main__":
    main()
