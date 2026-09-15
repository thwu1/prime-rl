#!/usr/bin/env python3
"""
Diagnostic validation runner for the ET engine.
Compares engine output against golden reference values from
the Fallon NV AgriMet station.

Usage:
  python3 validate_runner.py [daily|hourly|decomp|all]

"""

import json
import math
import sys
import traceback


def load_data():
    with open('/app/data/station.json') as f:
        station = json.load(f)
    with open('/app/data/golden_values.json') as f:
        golden = json.load(f)
    return station, golden


def convert_inputs(station):
    """Convert field-unit observations to SI for the ET engine API."""
    lat_rad = station['latitude_deg'] * math.pi / 180.0
    lon_rad = station['longitude_deg'] * math.pi / 180.0

    obs = station['daily']
    daily = dict(
        tmin=(obs['tmin_fahrenheit'] - 32.0) * 5.0 / 9.0,
        tmax=(obs['tmax_fahrenheit'] - 32.0) * 5.0 / 9.0,
        ea=obs['ea_kpa'],
        rs=obs['rs_langley'] * 0.041868,
        uz=obs['wind_speed_mph'] * 0.44704,
        zw=station['anemometer_height_m'],
        elev=station['elevation_m'],
        lat=lat_rad,
        doy=obs['doy'],
    )

    hobs = station['hourly']
    hourly = dict(
        tmean=(hobs['tmean_fahrenheit'] - 32.0) * 5.0 / 9.0,
        ea=hobs['ea_kpa'],
        rs=hobs['rs_langley'] * 0.041868,
        uz=hobs['wind_speed_mph'] * 0.44704,
        zw=station['anemometer_height_m'],
        elev=station['elevation_m'],
        lat=lat_rad,
        lon=lon_rad,
        doy=hobs['doy'],
        time=hobs['time_utc'],
    )

    return daily, hourly


def check_value(name, actual, expected, rel_tol=1e-6):
    if abs(expected) < 1e-15:
        err = abs(actual)
        ok = err < 1e-10
        err_str = f"abs={err:.2e}"
    else:
        err = abs(actual - expected) / abs(expected)
        ok = err < rel_tol
        err_str = f"rel={err:.2e}"
    status = "PASS" if ok else "FAIL"
    print(f"  {status}: {name:15s} = {actual:20.12f}  (expected {expected:20.12f}, {err_str})")
    return ok


def check_daily(station, golden):
    sys.path.insert(0, '/app')
    from et_engine import compute_daily

    daily_inputs, _ = convert_inputs(station)
    all_pass = True

    for method_name, golden_key in [('asce', 'daily_asce'),
                                     ('refet', 'daily_refet')]:
        print(f"\n--- Daily {method_name.upper()} ---")
        try:
            r = compute_daily(
                daily_inputs['tmin'], daily_inputs['tmax'], daily_inputs['ea'],
                daily_inputs['rs'], daily_inputs['uz'], daily_inputs['zw'],
                daily_inputs['elev'], daily_inputs['lat'], daily_inputs['doy'],
                method=method_name
            )
            for name, expected in golden[golden_key].items():
                if name in r:
                    if not check_value(name, r[name], expected):
                        all_pass = False
                else:
                    print(f"  MISSING: key '{name}' not in output dict")
                    all_pass = False
        except Exception as e:
            print(f"  ERROR: {e}")
            traceback.print_exc()
            all_pass = False

    return all_pass


def check_hourly(station, golden):
    sys.path.insert(0, '/app')
    from et_engine import compute_hourly

    _, hourly_inputs = convert_inputs(station)
    all_pass = True

    for method_name, golden_key in [('asce', 'hourly_asce'),
                                     ('refet', 'hourly_refet')]:
        print(f"\n--- Hourly {method_name.upper()} ---")
        try:
            r = compute_hourly(
                hourly_inputs['tmean'], hourly_inputs['ea'], hourly_inputs['rs'],
                hourly_inputs['uz'], hourly_inputs['zw'], hourly_inputs['elev'],
                hourly_inputs['lat'], hourly_inputs['lon'], hourly_inputs['doy'],
                hourly_inputs['time'], method=method_name
            )
            for name, expected in golden[golden_key].items():
                if name in r:
                    if not check_value(name, r[name], expected, rel_tol=1e-5):
                        all_pass = False
                else:
                    print(f"  MISSING: key '{name}' not in output dict")
                    all_pass = False
        except Exception as e:
            print(f"  ERROR: {e}")
            traceback.print_exc()
            all_pass = False

    return all_pass


def check_decomp(station, golden):
    sys.path.insert(0, '/app')
    from et_engine import decompose_daily_divergence

    daily_inputs, _ = convert_inputs(station)

    print(f"\n--- Decomposition (ETr) ---")
    all_pass = True
    try:
        d = decompose_daily_divergence(
            daily_inputs['tmin'], daily_inputs['tmax'], daily_inputs['ea'],
            daily_inputs['rs'], daily_inputs['uz'], daily_inputs['zw'],
            daily_inputs['elev'], daily_inputs['lat'], daily_inputs['doy'],
            surface='etr'
        )
        expected_total = golden['daily_asce']['etr'] - golden['daily_refet']['etr']
        if not check_value('total', d['total'], expected_total):
            all_pass = False

        required = ['air_pressure', 'es_slope', 'declination',
                    'solar_constant', 'clear_sky_radiation', 'residual']
        for key in required:
            if key in d:
                print(f"  FOUND:  {key:25s} = {d[key]:+.10f}")
            else:
                print(f"  MISSING: key '{key}'")
                all_pass = False

        if all(k in d for k in required):
            contrib_sum = sum(d[k] for k in required)
            diff = abs(contrib_sum - d['total'])
            if diff < 1e-10:
                print(f"  PASS:  contributions + residual sum to total (diff={diff:.2e})")
            else:
                print(f"  FAIL:  sum={contrib_sum:.12f} vs total={d['total']:.12f}")
                all_pass = False
    except Exception as e:
        print(f"  ERROR: {e}")
        traceback.print_exc()
        all_pass = False

    return all_pass


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    station, golden = load_data()
    results = {}

    if mode in ('all', 'daily'):
        results['daily'] = check_daily(station, golden)
    if mode in ('all', 'hourly'):
        results['hourly'] = check_hourly(station, golden)
    if mode in ('all', 'decomp'):
        results['decomp'] = check_decomp(station, golden)

    print("\n" + "=" * 60)
    for name, passed in results.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print("=" * 60)

    if all(results.values()):
        print("All validations passed.")
    else:
        print("Some validations failed.")
        sys.exit(1)


if __name__ == '__main__':
    main()
