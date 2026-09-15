#!/usr/bin/env python3
"""Canadian Forest Fire Weather Index System (CFFWIS) Calculator.

Computes DC, DMC, FFMC, ISI, BUI, FWI, DSR with WF93 fire season masking
and drought code overwintering between seasons.

References:
    Van Wagner, C.E. (1987). Development and Structure of the Canadian Forest
    Fire Weather Index System. Forestry Technical Report 35.
    Wang et al. (2015). Updated source code for calculating fire danger indices.
    Natural Resources Canada / Canadian Forest Service.
"""


import csv
import math
import sys

# =========================================================================
# Day length lookup tables by latitude band and month (1-indexed: Jan=1)
# Source: Van Wagner (1987), GFWED code
# Rows for DAY_LENGTHS: [-90,-30), [-30,-15), [-15,15), [15,30), [30,90]
# =========================================================================
DAY_LENGTHS = [
    [11.5, 10.5, 9.2, 7.9, 6.8, 6.2, 6.5, 7.4, 8.7, 10.0, 11.2, 11.8],
    [10.1, 9.6, 9.1, 8.5, 8.1, 7.8, 7.9, 8.3, 8.9, 9.4, 9.9, 10.2],
    [9.0] * 12,
    [7.9, 8.4, 8.9, 9.5, 9.9, 10.2, 10.1, 9.7, 9.1, 8.6, 8.1, 7.8],
    [6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0],
]

# Rows for DAY_LENGTH_FACTORS: [-90,-15), [-15,15), [15,90]
DAY_LENGTH_FACTORS = [
    [6.4, 5.0, 2.4, 0.4, -1.6, -1.6, -1.6, -1.6, -1.6, 0.9, 3.8, 5.8],
    [1.39] * 12,
    [-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6],
]

DC_START = 15.0
DMC_START = 6.0
FFMC_START = 85.0
CARRY_OVER_FRACTION = 0.75
WETTING_EFFICIENCY_FRACTION = 0.75


def day_length(lat, month):
    """Return average day length for a month at given latitude.

    Uses 5 latitude bands as defined by Van Wagner (1987).
    """
    if -30 > lat >= -90:
        return DAY_LENGTHS[0][month - 1]
    elif -15 > lat >= -30:
        return DAY_LENGTHS[1][month - 1]
    elif 15 > lat >= -15:
        return 9.0
    elif 30 > lat >= 15:
        return DAY_LENGTHS[3][month - 1]
    elif 90 >= lat >= 30:
        return DAY_LENGTHS[4][month - 1]
    else:
        raise ValueError(f"Invalid latitude: {lat}")


def day_length_factor(lat, month):
    """Return day length adjustment factor for DC computation.

    Uses 3 latitude bands. Values can be negative in winter.
    """
    if -15 > lat >= -90:
        return DAY_LENGTH_FACTORS[0][month - 1]
    elif 15 > lat >= -15:
        return 1.39
    elif 90 >= lat >= 15:
        return DAY_LENGTH_FACTORS[2][month - 1]
    else:
        raise ValueError(f"Invalid latitude: {lat}")


# =========================================================================
# CFFWIS Component Codes
# =========================================================================

def calc_ffmc(t, p, w, h, ffmc0):
    """Fine Fuel Moisture Code computation (Van Wagner Eqs. 1-10).

    Parameters
    ----------
    t : float - Noon temperature (C)
    p : float - 24h rainfall at noon (mm)
    w : float - Noon wind speed (km/h)
    h : float - Noon relative humidity (%)
    ffmc0 : float - Previous FFMC value

    Returns
    -------
    float - Current FFMC value
    """
    mo = (147.2 * (101.0 - ffmc0)) / (59.5 + ffmc0)  # Eq.1

    if p > 1.5:  # Eq.2 rain check
        rf = p - 1.5  # Effective rainfall
        if mo > 150.0:
            mo = (mo + 42.5 * rf * math.exp(-100.0 / (251.0 - mo)) *
                  (1.0 - math.exp(-6.93 / rf)) +
                  0.0015 * (mo - 150.0) ** 2 * math.sqrt(rf))  # Eq.3b
        else:
            mo = (mo + 42.5 * rf * math.exp(-100.0 / (251.0 - mo)) *
                  (1.0 - math.exp(-6.93 / rf)))  # Eq.3a
        mo = min(mo, 250.0)

    # Equilibrium moisture content for drying
    ed = (0.942 * h ** 0.679 + 11.0 * math.exp((h - 100.0) / 10.0) +
          0.18 * (21.1 - t) * (1.0 - 1.0 / math.exp(0.1150 * h)))  # Eq.4

    if mo < ed:
        # Wetting phase
        ew = (0.618 * h ** 0.753 + 10.0 * math.exp((h - 100.0) / 10.0) +
              0.18 * (21.1 - t) * (1.0 - 1.0 / math.exp(0.115 * h)))  # Eq.5
        if mo < ew:
            kl = (0.424 * (1.0 - ((100.0 - h) / 100.0) ** 1.7) +
                  0.0694 * math.sqrt(w) *
                  (1.0 - ((100.0 - h) / 100.0) ** 8))  # Eq.7a
            kw = kl * 0.581 * math.exp(0.0365 * t)  # Eq.7b
            m = ew - (ew - mo) / 10.0 ** kw  # Eq.9
        else:
            m = mo
    elif mo == ed:
        m = mo
    else:
        # Drying phase
        kl = (0.424 * (1.0 - (h / 100.0) ** 1.7) +
              0.0694 * math.sqrt(w) *
              (1.0 - (h / 100.0) ** 8))  # Eq.6a
        kw = kl * 0.581 * math.exp(0.0365 * t)  # Eq.6b
        m = ed + (mo - ed) / 10.0 ** kw  # Eq.8

    ffmc = (59.5 * (250.0 - m)) / (147.2 + m)  # Eq.10
    return max(0.0, min(101.0, ffmc))


def calc_dmc(t, p, h, month, lat, dmc0):
    """Duff Moisture Code computation (Van Wagner Eqs. 11-17).

    Parameters
    ----------
    t : float - Noon temperature (C)
    p : float - 24h rainfall (mm)
    h : float - Noon relative humidity (%)
    month : int - Month of year (1-12)
    lat : float - Latitude (degrees N)
    dmc0 : float - Previous DMC value

    Returns
    -------
    float - Current DMC value
    """
    if math.isnan(dmc0):
        return float('nan')

    # Day length for DMC drying rate
    dl = day_length_factor(lat, month)  # Effective day length

    if t < -1.1:
        rk = 0.0
    else:
        rk = 1.894 * (t + 1.1) * (100.0 - h) * dl * 0.0001  # Eqs.16-17

    if p > 1.5:
        ra = p
        rw = 0.92 * ra - 1.27  # Eq.11
        wmi = 20.0 + 280.0 / math.exp(0.023 * dmc0)  # Eq.12
        if dmc0 <= 33.0:
            b = 100.0 / (0.5 + 0.3 * dmc0)  # Eq.13a
        elif dmc0 <= 65.0:
            b = 14.0 - 1.3 * math.log(dmc0)  # Eq.13b
        else:
            b = 6.2 * math.log(dmc0) - 17.2  # Eq.13c
        wmr = wmi + (1000.0 * rw) / (48.77 + b * rw)  # Eq.14
        pr_val = 43.43 * (5.6348 - math.log(wmr - 20.0))  # Eq.15
    else:
        pr_val = dmc0

    pr_val = max(pr_val, 0.0)
    dmc = pr_val + rk
    return max(dmc, 0.0)


def calc_dc(t, p, month, lat, dc0):
    """Drought Code computation (Van Wagner Eqs. 18-22).

    Parameters
    ----------
    t : float - Noon temperature (C)
    p : float - 24h rainfall (mm)
    month : int - Month of year (1-12)
    lat : float - Latitude (degrees N)
    dc0 : float - Previous DC value

    Returns
    -------
    float - Current DC value
    """
    fl = day_length_factor(lat, month)

    t_eff = max(t, -2.8)
    pe = (0.36 * (t_eff + 2.8) + fl) / 2.0  # Eq.22
    pe = max(pe, 0.0)

    if p > 2.8:
        ra = p
        rw = 0.83 * ra - 1.27  # Eq.18 (Rd)
        smi = 800.0 * math.exp(max(-dc0 / 400.0, -700))  # Eq.19 (Qo)
        dr = dc0 + 400.0 * math.log(1.0 + (3.937 * rw) / smi)  # Eqs.20-21
        if dr > 0.0:
            dc = dr + pe
        elif math.isnan(dc0):
            dc = float('nan')
        else:
            dc = pe
    else:
        dc = dc0 + pe

    return dc


def calc_isi(ws, ffmc):
    """Initial Spread Index (Van Wagner Eqs. 25-26).

    Parameters
    ----------
    ws : float - Noon wind speed (km/h)
    ffmc : float - Fine Fuel Moisture Code

    Returns
    -------
    float - Initial Spread Index
    """
    mo = 147.2 * (101.0 - ffmc) / (59.5 + ffmc)  # Eq.1
    ff = 19.1152 * math.exp(mo * -0.1386) * (1.0 + mo ** 5.13 / 49300000.0)  # Eq.25
    isi = ff * math.exp(0.05039 * ws)  # Eq.26
    return isi


def calc_bui(dmc, dc):
    """Build-Up Index (Van Wagner Eq. 27).

    Parameters
    ----------
    dmc : float - Duff Moisture Code
    dc : float - Drought Code

    Returns
    -------
    float - Build-Up Index
    """
    if dmc == 0 and dc == 0:
        return 0.0
    if dmc <= 0.4 * dc:
        bui = (0.8 * dc * dmc) / (dmc + 0.4 * dc)  # Eq.27a
    else:
        bui = dmc - (1.0 - 0.8 * dc / (dmc + 0.4 * dc)) * \
              (0.92 + (0.0114 * dmc) ** 1.7)  # Eq.27b
    return max(bui, 0.0)


def calc_fwi(isi, bui):
    """Fire Weather Index (Van Wagner Eqs. 28-30).

    Parameters
    ----------
    isi : float - Initial Spread Index
    bui : float - Build-Up Index

    Returns
    -------
    float - Fire Weather Index
    """
    if bui > 80.0:
        fwi = 0.1 * isi * (0.626 * bui ** 0.809 + 2.0)  # Eq.28a
    else:
        fwi = 0.1 * isi * (1000.0 / (25.0 + 108.64 /
              math.exp(0.023 * bui)))  # Eq.28b

    if fwi > 1.0:
        fwi = math.exp(2.72 * (0.434 * math.log(fwi)) ** 0.647)  # Eq.30b

    return fwi


def calc_dsr(fwi):
    """Daily Severity Rating.

    Parameters
    ----------
    fwi : float - Fire Weather Index

    Returns
    -------
    float - Daily Severity Rating
    """
    return 0.0272 * fwi ** 1.77


# =========================================================================
# Fire Season Determination
# =========================================================================

def fire_season_wf93(temps, start_thresh=12.0, end_thresh=5.0, n_days=3):
    """Compute fire season mask using the WF93 method.

    Wotton & Flannigan (1993): fire season starts when N consecutive days
    exceed start_thresh and ends when N consecutive days fall below
    end_thresh. In WF93, the check uses the N previous days EXCLUDING
    the current day.

    Parameters
    ----------
    temps : list[float] - Daily temperatures
    start_thresh : float - Temperature threshold to start season (C)
    end_thresh : float - Temperature threshold to end season (C)
    n_days : int - Number of consecutive days required

    Returns
    -------
    list[bool] - Fire season mask (True = active)
    """
    n = len(temps)
    mask = [False] * n

    for i in range(n_days + 1, n):
        # WF93: check the N days BEFORE current day (EXCLUDING current)
        window = temps[i - n_days:i]

        start_up = all(t > start_thresh for t in window)
        shut_down = all(t < end_thresh for t in window)

        mask[i] = (mask[i - 1] or start_up) and not shut_down

    return mask


# =========================================================================
# Overwintering
# =========================================================================

def overwintering_dc(last_dc, winter_precip, a=CARRY_OVER_FRACTION,
                     b=WETTING_EFFICIENCY_FRACTION, min_dc=DC_START):
    """Compute overwintered drought code for start of new fire season.

    Based on Van Wagner (1985) and McElhinny et al. (2020).

    Parameters
    ----------
    last_dc : float - Last DC value from previous fire season
    winter_precip : float - Total precipitation accumulated over winter (mm)
    a : float - Carry-over fraction (0.5-1.0)
    b : float - Wetting efficiency fraction (0.5-0.9)
    min_dc : float - Minimum starting DC value

    Returns
    -------
    float - Overwintered DC value
    """
    if math.isnan(last_dc) or math.isnan(winter_precip):
        return float('nan')

    qf = 800.0 * math.exp(-last_dc / 400.0)  # Fall moisture equivalent
    qs = a * qf + b * (3.94 * winter_precip)  # Spring moisture
    if qs <= 0:
        return min_dc
    dcs = 400.0 * math.log(qs / 800.0)  # Spring DC
    return max(dcs, min_dc)


# =========================================================================
# Main Computation
# =========================================================================

def compute_fwi(input_file, output_file):
    """Read weather data, compute CFFWIS indices, write output.

    Processes each station independently with WF93 fire season masking
    and drought code overwintering between seasons.
    """
    # Read input data grouped by station
    station_data = {}
    with open(input_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = int(row['station_id'])
            if sid not in station_data:
                station_data[sid] = []
            station_data[sid].append({
                'date': row['date'],
                'lat': float(row['lat']),
                'tas': float(row['tas_degC']),
                'pr': float(row['pr_mm']),
                'hurs': float(row['hurs_pct']),
                'sfcWind': float(row['sfcWind_kmh']),
            })

    results = []

    for sid in sorted(station_data.keys()):
        sdata = station_data[sid]
        lat = sdata[0]['lat']
        n = len(sdata)

        # Fire season mask
        temps = [d['tas'] for d in sdata]
        season = fire_season_wf93(temps)

        # State variables
        dc = float('nan')
        dmc = float('nan')
        ffmc = float('nan')

        # Overwintering state
        last_dc = float('nan')
        winter_pr = 0.0
        in_season = False

        for i in range(n):
            d = sdata[i]
            dt = d['date']
            month = int(dt.split('-')[1])

            prev_in_season = in_season
            in_season = season[i]

            if in_season and not prev_in_season:
                # Start of fire season
                if not math.isnan(last_dc):
                    dc = overwintering_dc(last_dc, winter_pr)
                else:
                    dc = DC_START
                dmc = DMC_START
                ffmc = FFMC_START
                winter_pr = 0.0
            elif not in_season and prev_in_season:
                # End of fire season
                last_dc = dc
                winter_pr = d['pr']
                dc = float('nan')
                dmc = float('nan')
                ffmc = float('nan')
            elif not in_season:
                # Winter - accumulate precipitation
                winter_pr += d['pr']

            if in_season:
                ffmc = calc_ffmc(d['tas'], d['pr'], d['sfcWind'],
                                 d['hurs'], ffmc)
                dmc = calc_dmc(d['tas'], d['pr'], d['hurs'],
                               month, lat, dmc)
                dc = calc_dc(d['tas'], d['pr'], month, lat, dc)
                isi = calc_isi(d['sfcWind'], ffmc)
                bui = calc_bui(dmc, dc)
                fwi = calc_fwi(isi, bui)
                dsr = calc_dsr(fwi)
            else:
                isi = float('nan')
                bui = float('nan')
                fwi = float('nan')
                dsr = float('nan')

            results.append({
                'date': dt,
                'station_id': sid,
                'DC': dc,
                'DMC': dmc,
                'FFMC': ffmc,
                'ISI': isi,
                'BUI': bui,
                'FWI': fwi,
                'DSR': dsr,
                'season_mask': 1 if in_season else 0,
            })

    # Write output CSV
    fieldnames = ['date', 'station_id', 'DC', 'DMC', 'FFMC',
                  'ISI', 'BUI', 'FWI', 'DSR', 'season_mask']
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            out_row = {}
            for k, v in r.items():
                if isinstance(v, float):
                    if math.isnan(v):
                        out_row[k] = ''
                    else:
                        out_row[k] = f'{v:.6f}'
                else:
                    out_row[k] = v
            writer.writerow(out_row)

    print(f"Wrote {len(results)} rows to {output_file}")


if __name__ == '__main__':
    compute_fwi('/app/weather_data.csv', '/app/fwi_output.csv')
