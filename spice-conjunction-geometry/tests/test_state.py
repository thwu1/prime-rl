"""
Tests for the SPICE ephemeris computation pipeline.

Independently computes reference values using SpiceyPy and compares
against the solver's output in /app/results.json.
"""


import pytest
import json
import os
import math
import urllib.request
import numpy as np
import spiceypy as spice

RESULTS_FILE = '/app/results.json'
KERNELS_DIR = '/tmp/test_kernels'

KERNEL_URLS = {
    'naif0012.tls': 'https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/naif0012.tls',
    'de440s.bsp': 'https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440s.bsp',
    'pck00011.tpc': 'https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/pck00011.tpc',
    'mar099s.bsp': 'https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/satellites/mar099s.bsp',
}

SPEED_OF_LIGHT_KM_S = 299792.458


def _download_kernel(name):
    path = os.path.join(KERNELS_DIR, name)
    if not os.path.exists(path):
        os.makedirs(KERNELS_DIR, exist_ok=True)
        urllib.request.urlretrieve(KERNEL_URLS[name], path)
    return path


def _lon_to_360(lon_rad):
    deg = lon_rad * spice.dpr()
    if deg < 0:
        deg += 360.0
    return deg


@pytest.fixture(scope='session')
def load_kernels():
    """Download and load all required SPICE kernels."""
    spice.kclear()
    for name in KERNEL_URLS:
        path = _download_kernel(name)
        spice.furnsh(path)
    yield
    spice.kclear()


@pytest.fixture(scope='session')
def reference_values(load_kernels):
    """Compute all reference values independently."""
    refs = {}

    # ---- mars_equatorial ----
    et = spice.str2et('2024 JAN 15 12:00:00 UTC')
    pos, lt = spice.spkpos('MARS BARYCENTER', et, 'J2000', 'LT+S', 'EARTH')
    r, lon, lat = spice.reclat(pos)
    pos_ecl, _ = spice.spkpos(
        'MARS BARYCENTER', et, 'ECLIPJ2000', 'LT+S', 'EARTH'
    )
    _, lon_e, lat_e = spice.reclat(pos_ecl)
    refs['mars_equatorial'] = {
        'position_km': [float(pos[0]), float(pos[1]), float(pos[2])],
        'ra_deg': _lon_to_360(lon),
        'dec_deg': float(lat * spice.dpr()),
        'range_km': float(spice.vnorm(pos)),
        'light_time_sec': float(lt),
        'ecliptic_lon_deg': _lon_to_360(lon_e),
        'ecliptic_lat_deg': float(lat_e * spice.dpr()),
    }

    # ---- jupiter_phase ----
    et = spice.str2et('2024 JUN 01 00:00:00 UTC')
    pos, lt = spice.spkpos(
        'JUPITER BARYCENTER', et, 'J2000', 'CN+S', 'EARTH'
    )
    r, lon, lat = spice.reclat(pos)
    pos_ecl, _ = spice.spkpos(
        'JUPITER BARYCENTER', et, 'ECLIPJ2000', 'CN+S', 'EARTH'
    )
    _, lon_e, lat_e = spice.reclat(pos_ecl)
    # Phase angle: Sun-Jupiter-Earth, vectors FROM Jupiter
    pos_sun_j, _ = spice.spkpos(
        'SUN', et, 'J2000', 'CN+S', 'JUPITER BARYCENTER'
    )
    pos_earth_j, _ = spice.spkpos(
        'EARTH', et, 'J2000', 'CN+S', 'JUPITER BARYCENTER'
    )
    phase = float(spice.vsep(pos_sun_j, pos_earth_j) * spice.dpr())
    refs['jupiter_phase'] = {
        'position_km': [float(pos[0]), float(pos[1]), float(pos[2])],
        'ra_deg': _lon_to_360(lon),
        'dec_deg': float(lat * spice.dpr()),
        'range_km': float(spice.vnorm(pos)),
        'light_time_sec': float(lt),
        'ecliptic_lon_deg': _lon_to_360(lon_e),
        'ecliptic_lat_deg': float(lat_e * spice.dpr()),
        'phase_angle_deg': phase,
    }

    # ---- phobos_position ----
    et = spice.str2et('2024 MAR 01 00:00:00 UTC')
    pos, lt = spice.spkpos('PHOBOS', et, 'J2000', 'LT+S', 'EARTH')
    r, lon, lat = spice.reclat(pos)
    refs['phobos_position'] = {
        'position_km': [float(pos[0]), float(pos[1]), float(pos[2])],
        'ra_deg': _lon_to_360(lon),
        'dec_deg': float(lat * spice.dpr()),
        'range_km': float(spice.vnorm(pos)),
        'light_time_sec': float(lt),
    }

    # ---- saturn_velocity ----
    et = spice.str2et('2024 SEP 22 06:00:00 UTC')
    pos, lt = spice.spkpos(
        'SATURN BARYCENTER', et, 'J2000', 'LT+S', 'MARS BARYCENTER'
    )
    r, lon, lat = spice.reclat(pos)
    state, _ = spice.spkezr(
        'SATURN BARYCENTER', et, 'J2000', 'LT+S', 'MARS BARYCENTER'
    )
    vel = [float(state[3]), float(state[4]), float(state[5])]
    speed = math.sqrt(sum(v * v for v in vel))
    pos_ecl, _ = spice.spkpos(
        'SATURN BARYCENTER', et, 'ECLIPJ2000', 'LT+S', 'MARS BARYCENTER'
    )
    _, lon_e, lat_e = spice.reclat(pos_ecl)
    refs['saturn_velocity'] = {
        'position_km': [float(pos[0]), float(pos[1]), float(pos[2])],
        'ra_deg': _lon_to_360(lon),
        'dec_deg': float(lat * spice.dpr()),
        'range_km': float(spice.vnorm(pos)),
        'light_time_sec': float(lt),
        'velocity_km_s': vel,
        'speed_km_s': speed,
        'ecliptic_lon_deg': _lon_to_360(lon_e),
        'ecliptic_lat_deg': float(lat_e * spice.dpr()),
    }

    return refs


@pytest.fixture(scope='session')
def results():
    """Load the solver's results from JSON."""
    assert os.path.exists(RESULTS_FILE), f'{RESULTS_FILE} not found'
    with open(RESULTS_FILE) as f:
        data = json.load(f)
    assert isinstance(data, dict), 'results.json must be a JSON object'
    return data


# ================================================================== #
# Structural tests
# ================================================================== #

def test_results_file_exists():
    assert os.path.exists(RESULTS_FILE), f'{RESULTS_FILE} not found'


def test_results_valid_json():
    with open(RESULTS_FILE) as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_all_scenarios_present(results):
    for sid in ['mars_equatorial', 'jupiter_phase',
                'phobos_position', 'saturn_velocity']:
        assert sid in results, f'Missing scenario: {sid}'


def test_no_scenario_errors(results):
    for sid in ['mars_equatorial', 'jupiter_phase',
                'phobos_position', 'saturn_velocity']:
        assert 'error' not in results[sid], \
            f'Scenario {sid} has error: {results[sid].get("error")}'


# ================================================================== #
# Range validity checks
# ================================================================== #

def test_all_ra_in_range(results):
    for sid in ['mars_equatorial', 'jupiter_phase',
                'phobos_position', 'saturn_velocity']:
        ra = results[sid]['ra_deg']
        assert 0 <= ra < 360, f'{sid} RA={ra} not in [0,360)'


def test_all_dec_in_range(results):
    for sid in ['mars_equatorial', 'jupiter_phase',
                'phobos_position', 'saturn_velocity']:
        dec = results[sid]['dec_deg']
        assert -90 <= dec <= 90, f'{sid} Dec={dec} not in [-90,90]'


def test_ecliptic_lon_in_range(results):
    for sid in ['mars_equatorial', 'jupiter_phase', 'saturn_velocity']:
        lon = results[sid]['ecliptic_lon_deg']
        assert 0 <= lon < 360, f'{sid} ecl_lon={lon} not in [0,360)'


def test_ecliptic_lat_in_range(results):
    for sid in ['mars_equatorial', 'jupiter_phase', 'saturn_velocity']:
        lat = results[sid]['ecliptic_lat_deg']
        assert -90 <= lat <= 90, f'{sid} ecl_lat={lat} not in [-90,90]'


def test_phase_angle_in_range(results):
    pa = results['jupiter_phase']['phase_angle_deg']
    assert 0 <= pa <= 180, f'Phase angle {pa} not in [0, 180]'


# ================================================================== #
# Mars equatorial scenario
# ================================================================== #

def test_mars_position_km(results, reference_values):
    ref = reference_values['mars_equatorial']['position_km']
    sol = results['mars_equatorial']['position_km']
    for i in range(3):
        assert abs(sol[i] - ref[i]) / max(abs(ref[i]), 1.0) < 0.001, \
            f'Mars position[{i}]: ref={ref[i]:.3f}, got={sol[i]:.3f}'


def test_mars_ra(results, reference_values):
    ref = reference_values['mars_equatorial']['ra_deg']
    sol = results['mars_equatorial']['ra_deg']
    assert abs(sol - ref) < 0.01, \
        f'Mars RA: ref={ref:.6f}, got={sol:.6f}'


def test_mars_dec(results, reference_values):
    ref = reference_values['mars_equatorial']['dec_deg']
    sol = results['mars_equatorial']['dec_deg']
    assert abs(sol - ref) < 0.01, \
        f'Mars Dec: ref={ref:.6f}, got={sol:.6f}'


def test_mars_range(results, reference_values):
    ref = reference_values['mars_equatorial']['range_km']
    sol = results['mars_equatorial']['range_km']
    assert abs(sol - ref) / ref < 0.001, \
        f'Mars range: ref={ref:.3f}, got={sol:.3f}'


def test_mars_light_time(results, reference_values):
    ref = reference_values['mars_equatorial']['light_time_sec']
    sol = results['mars_equatorial']['light_time_sec']
    assert abs(sol - ref) / ref < 0.001, \
        f'Mars LT: ref={ref:.6f}, got={sol:.6f}'


def test_mars_ecliptic_lon(results, reference_values):
    ref = reference_values['mars_equatorial']['ecliptic_lon_deg']
    sol = results['mars_equatorial']['ecliptic_lon_deg']
    assert abs(sol - ref) < 0.01, \
        f'Mars ecl lon: ref={ref:.6f}, got={sol:.6f}'


def test_mars_ecliptic_lat(results, reference_values):
    ref = reference_values['mars_equatorial']['ecliptic_lat_deg']
    sol = results['mars_equatorial']['ecliptic_lat_deg']
    assert abs(sol - ref) < 0.01, \
        f'Mars ecl lat: ref={ref:.6f}, got={sol:.6f}'


def test_mars_range_lighttime_consistency(results):
    r = results['mars_equatorial']['range_km']
    lt = results['mars_equatorial']['light_time_sec']
    c_computed = r / lt
    assert abs(c_computed - SPEED_OF_LIGHT_KM_S) / SPEED_OF_LIGHT_KM_S < 0.0001, \
        f'range/lt = {c_computed:.3f}, expected ~{SPEED_OF_LIGHT_KM_S}'


# ================================================================== #
# Jupiter phase scenario
# ================================================================== #

def test_jupiter_position_km(results, reference_values):
    ref = reference_values['jupiter_phase']['position_km']
    sol = results['jupiter_phase']['position_km']
    for i in range(3):
        assert abs(sol[i] - ref[i]) / max(abs(ref[i]), 1.0) < 0.001, \
            f'Jupiter position[{i}]: ref={ref[i]:.3f}, got={sol[i]:.3f}'


def test_jupiter_ra(results, reference_values):
    ref = reference_values['jupiter_phase']['ra_deg']
    sol = results['jupiter_phase']['ra_deg']
    assert abs(sol - ref) < 0.01, \
        f'Jupiter RA: ref={ref:.6f}, got={sol:.6f}'


def test_jupiter_dec(results, reference_values):
    ref = reference_values['jupiter_phase']['dec_deg']
    sol = results['jupiter_phase']['dec_deg']
    assert abs(sol - ref) < 0.01, \
        f'Jupiter Dec: ref={ref:.6f}, got={sol:.6f}'


def test_jupiter_range(results, reference_values):
    ref = reference_values['jupiter_phase']['range_km']
    sol = results['jupiter_phase']['range_km']
    assert abs(sol - ref) / ref < 0.001, \
        f'Jupiter range: ref={ref:.3f}, got={sol:.3f}'


def test_jupiter_light_time(results, reference_values):
    ref = reference_values['jupiter_phase']['light_time_sec']
    sol = results['jupiter_phase']['light_time_sec']
    assert abs(sol - ref) / ref < 0.001, \
        f'Jupiter LT: ref={ref:.6f}, got={sol:.6f}'


def test_jupiter_ecliptic_lon(results, reference_values):
    ref = reference_values['jupiter_phase']['ecliptic_lon_deg']
    sol = results['jupiter_phase']['ecliptic_lon_deg']
    assert abs(sol - ref) < 0.01, \
        f'Jupiter ecl lon: ref={ref:.6f}, got={sol:.6f}'


def test_jupiter_ecliptic_lat(results, reference_values):
    ref = reference_values['jupiter_phase']['ecliptic_lat_deg']
    sol = results['jupiter_phase']['ecliptic_lat_deg']
    assert abs(sol - ref) < 0.01, \
        f'Jupiter ecl lat: ref={ref:.6f}, got={sol:.6f}'


def test_jupiter_phase_angle(results, reference_values):
    ref = reference_values['jupiter_phase']['phase_angle_deg']
    sol = results['jupiter_phase']['phase_angle_deg']
    assert abs(sol - ref) < 0.1, \
        f'Jupiter phase angle: ref={ref:.6f}, got={sol:.6f}'


def test_jupiter_range_lighttime_consistency(results):
    r = results['jupiter_phase']['range_km']
    lt = results['jupiter_phase']['light_time_sec']
    c_computed = r / lt
    assert abs(c_computed - SPEED_OF_LIGHT_KM_S) / SPEED_OF_LIGHT_KM_S < 0.0001, \
        f'range/lt = {c_computed:.3f}, expected ~{SPEED_OF_LIGHT_KM_S}'


# ================================================================== #
# Phobos position scenario
# ================================================================== #

def test_phobos_has_no_error(results):
    assert 'error' not in results.get('phobos_position', {}), \
        f'Phobos error: {results.get("phobos_position", {}).get("error")}'


def test_phobos_position_km(results, reference_values):
    ref = reference_values['phobos_position']['position_km']
    sol = results['phobos_position']['position_km']
    for i in range(3):
        assert abs(sol[i] - ref[i]) / max(abs(ref[i]), 1.0) < 0.005, \
            f'Phobos position[{i}]: ref={ref[i]:.3f}, got={sol[i]:.3f}'


def test_phobos_ra(results, reference_values):
    ref = reference_values['phobos_position']['ra_deg']
    sol = results['phobos_position']['ra_deg']
    assert abs(sol - ref) < 0.05, \
        f'Phobos RA: ref={ref:.6f}, got={sol:.6f}'


def test_phobos_dec(results, reference_values):
    ref = reference_values['phobos_position']['dec_deg']
    sol = results['phobos_position']['dec_deg']
    assert abs(sol - ref) < 0.05, \
        f'Phobos Dec: ref={ref:.6f}, got={sol:.6f}'


def test_phobos_range(results, reference_values):
    ref = reference_values['phobos_position']['range_km']
    sol = results['phobos_position']['range_km']
    assert abs(sol - ref) / ref < 0.001, \
        f'Phobos range: ref={ref:.3f}, got={sol:.3f}'


def test_phobos_light_time(results, reference_values):
    ref = reference_values['phobos_position']['light_time_sec']
    sol = results['phobos_position']['light_time_sec']
    assert abs(sol - ref) / ref < 0.001, \
        f'Phobos LT: ref={ref:.6f}, got={sol:.6f}'


def test_phobos_range_lighttime_consistency(results):
    r = results['phobos_position']['range_km']
    lt = results['phobos_position']['light_time_sec']
    c_computed = r / lt
    assert abs(c_computed - SPEED_OF_LIGHT_KM_S) / SPEED_OF_LIGHT_KM_S < 0.0001, \
        f'Phobos range/lt = {c_computed:.3f}, expected ~{SPEED_OF_LIGHT_KM_S}'


# ================================================================== #
# Saturn velocity scenario
# ================================================================== #

def test_saturn_has_no_error(results):
    assert 'error' not in results.get('saturn_velocity', {}), \
        f'Saturn error: {results.get("saturn_velocity", {}).get("error")}'


def test_saturn_position_km(results, reference_values):
    ref = reference_values['saturn_velocity']['position_km']
    sol = results['saturn_velocity']['position_km']
    for i in range(3):
        assert abs(sol[i] - ref[i]) / max(abs(ref[i]), 1.0) < 0.001, \
            f'Saturn position[{i}]: ref={ref[i]:.3f}, got={sol[i]:.3f}'


def test_saturn_ra(results, reference_values):
    ref = reference_values['saturn_velocity']['ra_deg']
    sol = results['saturn_velocity']['ra_deg']
    assert abs(sol - ref) < 0.01, \
        f'Saturn RA: ref={ref:.6f}, got={sol:.6f}'


def test_saturn_dec(results, reference_values):
    ref = reference_values['saturn_velocity']['dec_deg']
    sol = results['saturn_velocity']['dec_deg']
    assert abs(sol - ref) < 0.01, \
        f'Saturn Dec: ref={ref:.6f}, got={sol:.6f}'


def test_saturn_range(results, reference_values):
    ref = reference_values['saturn_velocity']['range_km']
    sol = results['saturn_velocity']['range_km']
    assert abs(sol - ref) / ref < 0.001, \
        f'Saturn range: ref={ref:.3f}, got={sol:.3f}'


def test_saturn_light_time(results, reference_values):
    ref = reference_values['saturn_velocity']['light_time_sec']
    sol = results['saturn_velocity']['light_time_sec']
    assert abs(sol - ref) / ref < 0.001, \
        f'Saturn LT: ref={ref:.6f}, got={sol:.6f}'


def test_saturn_velocity_components(results, reference_values):
    ref = reference_values['saturn_velocity']['velocity_km_s']
    sol = results['saturn_velocity']['velocity_km_s']
    assert isinstance(sol, list) and len(sol) == 3, \
        f'velocity_km_s must be 3-element list, got {type(sol)}'
    for i in range(3):
        assert abs(sol[i] - ref[i]) < max(0.1, abs(ref[i]) * 0.01), \
            f'Saturn vel[{i}]: ref={ref[i]:.6f}, got={sol[i]:.6f}'


def test_saturn_speed(results, reference_values):
    ref = reference_values['saturn_velocity']['speed_km_s']
    sol = results['saturn_velocity']['speed_km_s']
    assert abs(sol - ref) / ref < 0.01, \
        f'Saturn speed: ref={ref:.6f}, got={sol:.6f}'


def test_saturn_speed_consistency(results):
    vel = results['saturn_velocity']['velocity_km_s']
    speed = results['saturn_velocity']['speed_km_s']
    computed_speed = math.sqrt(sum(v * v for v in vel))
    assert abs(speed - computed_speed) / max(speed, 0.001) < 0.001, \
        f'Speed inconsistency: speed={speed:.6f}, |vel|={computed_speed:.6f}'


def test_saturn_ecliptic_lon(results, reference_values):
    ref = reference_values['saturn_velocity']['ecliptic_lon_deg']
    sol = results['saturn_velocity']['ecliptic_lon_deg']
    assert abs(sol - ref) < 0.01, \
        f'Saturn ecl lon: ref={ref:.6f}, got={sol:.6f}'


def test_saturn_ecliptic_lat(results, reference_values):
    ref = reference_values['saturn_velocity']['ecliptic_lat_deg']
    sol = results['saturn_velocity']['ecliptic_lat_deg']
    assert abs(sol - ref) < 0.01, \
        f'Saturn ecl lat: ref={ref:.6f}, got={sol:.6f}'


def test_saturn_range_lighttime_consistency(results):
    r = results['saturn_velocity']['range_km']
    lt = results['saturn_velocity']['light_time_sec']
    c_computed = r / lt
    assert abs(c_computed - SPEED_OF_LIGHT_KM_S) / SPEED_OF_LIGHT_KM_S < 0.0001, \
        f'Saturn range/lt = {c_computed:.3f}, expected ~{SPEED_OF_LIGHT_KM_S}'
