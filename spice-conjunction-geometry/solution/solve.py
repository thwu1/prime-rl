#!/usr/bin/env python3
"""
Corrected SPICE ephemeris computation pipeline.

Fixes all defects from the original pipeline.py:
1. Meta-kernel PATH_VALUES pointed to /app/data instead of /app/kernels
   -> Bypassed by loading kernels directly
2. Missing Mars satellite SPK for Phobos
   -> Added mar099s.bsp download
3. reclat destructuring: (r, lat, lon) was wrong, correct is (r, lon, lat)
4. Ecliptic longitude not wrapped to [0, 360)
5. Phase angle computed from observer instead of from target
6. Velocity used spkpos (3-element) instead of spkezr (6-element state)
"""


import json
import os
import math
import urllib.request
import spiceypy as spice

KERNELS_DIR = '/app/kernels'
SCENARIOS_FILE = '/app/scenarios.json'
RESULTS_FILE = '/app/results.json'

KERNEL_URLS = {
    'naif0012.tls': 'https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/naif0012.tls',
    'de440s.bsp': 'https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440s.bsp',
    'pck00011.tpc': 'https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/pck00011.tpc',
    'mar099s.bsp': 'https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/satellites/mar099s.bsp',
}


def download_and_load_kernels():
    """Download and load all required SPICE kernels directly."""
    os.makedirs(KERNELS_DIR, exist_ok=True)
    for name, url in KERNEL_URLS.items():
        path = os.path.join(KERNELS_DIR, name)
        if not os.path.exists(path):
            print(f'Downloading {name}...')
            urllib.request.urlretrieve(url, path)
        spice.furnsh(path)


def lon_to_360(lon_rad):
    """Convert longitude in radians to degrees in [0, 360)."""
    deg = lon_rad * spice.dpr()
    if deg < 0:
        deg += 360.0
    return deg


def position_to_radec(pos):
    """Convert Cartesian position to RA/Dec in degrees.
    reclat returns (radius, longitude, latitude) -- NOT (r, lat, lon)."""
    r, lon, lat = spice.reclat(pos)
    ra_deg = lon_to_360(lon)
    dec_deg = lat * spice.dpr()
    return ra_deg, dec_deg, r


def position_to_ecliptic(target, observer, et, abcorr):
    """Compute ecliptic longitude [0,360) and latitude in degrees."""
    pos_ecl, _ = spice.spkpos(target, et, 'ECLIPJ2000', abcorr, observer)
    r, lon, lat = spice.reclat(pos_ecl)
    ecl_lon_deg = lon_to_360(lon)
    ecl_lat_deg = lat * spice.dpr()
    return ecl_lon_deg, ecl_lat_deg


def compute_phase_angle(target, observer, et, abcorr):
    """Compute phase angle (Sun-Target-Observer) in degrees.
    Vectors must be computed FROM the target, not from the observer."""
    pos_sun, _ = spice.spkpos('SUN', et, 'J2000', abcorr, target)
    pos_obs, _ = spice.spkpos(observer, et, 'J2000', abcorr, target)
    angle = spice.vsep(pos_sun, pos_obs) * spice.dpr()
    return angle


def compute_velocity(target, observer, et, frame, abcorr):
    """Compute velocity using spkezr (6-element state vector)."""
    state, lt = spice.spkezr(target, et, frame, abcorr, observer)
    vel = [float(state[3]), float(state[4]), float(state[5])]
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
    download_and_load_kernels()

    with open(SCENARIOS_FILE) as f:
        scenarios = json.load(f)

    results = {}
    for scenario in scenarios:
        sid = scenario['id']
        results[sid] = process_scenario(scenario)

    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)

    print(f'Results written to {RESULTS_FILE}')
    print(json.dumps(results, indent=2))
    spice.kclear()


if __name__ == '__main__':
    main()
