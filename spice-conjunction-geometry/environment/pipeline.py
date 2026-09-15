#!/usr/bin/env python3
"""SPICE ephemeris computation pipeline.

Loads SPICE kernels, computes geometric quantities for each scenario
defined in scenarios.json, and writes results to results.json.
"""

import json
import os
import math
import urllib.request
import spiceypy as spice

KERNELS_DIR = '/app/kernels'
META_KERNEL = '/app/kernels.tm'
SCENARIOS_FILE = '/app/scenarios.json'
RESULTS_FILE = '/app/results.json'

KERNEL_URLS = {
    'naif0012.tls': 'https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/naif0012.tls',
    'de440s.bsp': 'https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440s.bsp',
    'pck00011.tpc': 'https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/pck00011.tpc',
}


def download_kernels():
    """Download required SPICE kernels if not already present."""
    os.makedirs(KERNELS_DIR, exist_ok=True)
    for name, url in KERNEL_URLS.items():
        path = os.path.join(KERNELS_DIR, name)
        if not os.path.exists(path):
            print(f'Downloading {name}...')
            urllib.request.urlretrieve(url, path)


def position_to_radec(pos):
    """Convert Cartesian position vector to RA/Dec in degrees."""
    r, lat, lon = spice.reclat(pos)
    ra_deg = lon * spice.dpr()
    dec_deg = lat * spice.dpr()
    if ra_deg < 0:
        ra_deg += 360.0
    return ra_deg, dec_deg, r


def position_to_ecliptic(target, observer, et, abcorr):
    """Compute ecliptic longitude and latitude in degrees."""
    pos_ecl, _ = spice.spkpos(target, et, 'ECLIPJ2000', abcorr, observer)
    r, lon, lat = spice.reclat(pos_ecl)
    ecl_lon_deg = lon * spice.dpr()
    ecl_lat_deg = lat * spice.dpr()
    return ecl_lon_deg, ecl_lat_deg


def compute_phase_angle(target, observer, et, abcorr):
    """Compute the phase angle (Sun-Target-Observer) in degrees."""
    pos_sun, _ = spice.spkpos('SUN', et, 'J2000', abcorr, observer)
    pos_tgt, _ = spice.spkpos(target, et, 'J2000', abcorr, observer)
    angle = spice.vsep(pos_sun, pos_tgt) * spice.dpr()
    return angle


def compute_velocity(target, observer, et, frame, abcorr):
    """Compute target velocity relative to observer."""
    pos, lt = spice.spkpos(target, et, frame, abcorr, observer)
    vel = [float(pos[3]), float(pos[4]), float(pos[5])]
    speed = math.sqrt(sum(v * v for v in vel))
    return vel, speed


def process_scenario(scenario):
    """Process a single computation scenario and return results dict."""
    target = scenario['target']
    observer = scenario['observer']
    epoch = scenario['epoch']
    frame = scenario['frame']
    abcorr = scenario['abcorr']
    outputs = scenario['outputs']

    et = spice.str2et(epoch)
    pos, lt = spice.spkpos(target, et, frame, abcorr, observer)

    result = {}

    if 'position_km' in outputs:
        result['position_km'] = [float(pos[0]), float(pos[1]), float(pos[2])]

    if 'ra_deg' in outputs or 'dec_deg' in outputs:
        ra, dec, r = position_to_radec(pos)
        if 'ra_deg' in outputs:
            result['ra_deg'] = ra
        if 'dec_deg' in outputs:
            result['dec_deg'] = dec

    if 'range_km' in outputs:
        result['range_km'] = float(spice.vnorm(pos))

    if 'light_time_sec' in outputs:
        result['light_time_sec'] = float(lt)

    if 'ecliptic_lon_deg' in outputs or 'ecliptic_lat_deg' in outputs:
        ecl_lon, ecl_lat = position_to_ecliptic(
            target, observer, et, abcorr
        )
        if 'ecliptic_lon_deg' in outputs:
            result['ecliptic_lon_deg'] = ecl_lon
        if 'ecliptic_lat_deg' in outputs:
            result['ecliptic_lat_deg'] = ecl_lat

    if 'phase_angle_deg' in outputs:
        result['phase_angle_deg'] = compute_phase_angle(
            target, observer, et, abcorr
        )

    if 'velocity_km_s' in outputs or 'speed_km_s' in outputs:
        vel, speed = compute_velocity(target, observer, et, frame, abcorr)
        if 'velocity_km_s' in outputs:
            result['velocity_km_s'] = vel
        if 'speed_km_s' in outputs:
            result['speed_km_s'] = speed

    return result


def main():
    download_kernels()
    spice.furnsh(META_KERNEL)

    with open(SCENARIOS_FILE) as f:
        scenarios = json.load(f)

    results = {}
    for scenario in scenarios:
        sid = scenario['id']
        try:
            results[sid] = process_scenario(scenario)
        except Exception as e:
            print(f'Error processing scenario {sid}: {e}')
            results[sid] = {'error': str(e)}

    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)

    print(f'Results written to {RESULTS_FILE}')
    spice.kclear()


if __name__ == '__main__':
    main()
