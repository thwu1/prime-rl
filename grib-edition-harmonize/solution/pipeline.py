#!/usr/bin/env python3
"""GRIB data harmonization pipeline — complete solution.

"""

import json
import os
import subprocess
import eccodes
import numpy as np

DATA_DIR = '/app/data'
OUTPUT_DIR = '/app/output'
RULES_DIR = '/app/rules'
SPLIT_DIR = os.path.join(OUTPUT_DIR, 'split')
HARMONIZED_PATH = os.path.join(OUTPUT_DIR, 'harmonized.grib2')


def get_input_files():
    """Return sorted list of GRIB filenames in the data directory."""
    return sorted(f for f in os.listdir(DATA_DIR) if f.endswith('.grib'))


# ── Step 1: Inventory ────────────────────────────────────────────────────────

def create_inventory():
    inventory = []
    for fname in get_input_files():
        fpath = os.path.join(DATA_DIR, fname)
        with open(fpath, 'rb') as f:
            msg_num = 0
            while True:
                mid = eccodes.codes_grib_new_from_file(f)
                if mid is None:
                    break
                msg_num += 1
                vals = eccodes.codes_get_values(mid)
                inventory.append({
                    'filename': fname,
                    'messageNumber': msg_num,
                    'shortName': eccodes.codes_get(mid, 'shortName'),
                    'paramId': eccodes.codes_get(mid, 'paramId'),
                    'level': eccodes.codes_get(mid, 'level'),
                    'typeOfLevel': eccodes.codes_get(mid, 'typeOfLevel'),
                    'gridType': eccodes.codes_get(mid, 'gridType'),
                    'packingType': eccodes.codes_get(mid, 'packingType'),
                    'edition': eccodes.codes_get(mid, 'edition'),
                    'numberOfValues': len(vals),
                    'dataMin': round(float(np.min(vals)), 6),
                    'dataMax': round(float(np.max(vals)), 6),
                    'dataMean': round(float(np.mean(vals)), 6),
                })
                eccodes.codes_release(mid)
    return inventory


# ── Step 2: Write grib_filter rules ──────────────────────────────────────────

def write_harmonize_rules():
    rules = (
        '# Harmonize all messages to GRIB2 grid_simple 16-bit\n'
        'set edition = 2;\n'
        'set packingType = "grid_simple";\n'
        'set bitsPerValue = 16;\n'
        'write "/app/output/harmonized.grib2";\n'
    )
    with open(os.path.join(RULES_DIR, 'harmonize.rules'), 'w') as f:
        f.write(rules)


# ── Step 3: Run harmonization via grib_filter ────────────────────────────────

def run_harmonization():
    if os.path.exists(HARMONIZED_PATH):
        os.remove(HARMONIZED_PATH)

    input_paths = [os.path.join(DATA_DIR, f) for f in get_input_files()]
    rules_path = os.path.join(RULES_DIR, 'harmonize.rules')

    cmd = ['grib_filter', rules_path] + input_paths
    subprocess.run(cmd, check=True)


# ── Step 4: Split by parameter ───────────────────────────────────────────────

def split_by_parameter():
    with open(HARMONIZED_PATH, 'rb') as f:
        while True:
            mid = eccodes.codes_grib_new_from_file(f)
            if mid is None:
                break
            sn = eccodes.codes_get(mid, 'shortName')
            out_path = os.path.join(SPLIT_DIR, '{}.grib2'.format(sn))
            with open(out_path, 'ab') as fout:
                eccodes.codes_write(mid, fout)
            eccodes.codes_release(mid)


# ── Step 5: Derived quantities ───────────────────────────────────────────────

def compute_derived():
    # Collect all data by (shortName, level)
    data = {}  # key -> list of value arrays
    with open(HARMONIZED_PATH, 'rb') as f:
        while True:
            mid = eccodes.codes_grib_new_from_file(f)
            if mid is None:
                break
            sn = eccodes.codes_get(mid, 'shortName')
            lev = eccodes.codes_get(mid, 'level')
            vals = eccodes.codes_get_values(mid)
            key = (sn, lev)
            if key not in data:
                data[key] = []
            data[key].append(vals)
            eccodes.codes_release(mid)

    derived = []

    # Potential temperature at each level with temperature data
    t_levels = sorted({lev for (sn, lev) in data if sn == 't'})
    for lev in t_levels:
        all_vals = np.concatenate(data[('t', lev)])
        t_mean = float(np.mean(all_vals))
        theta = t_mean * (1000.0 / lev) ** 0.2856
        derived.append({
            'quantity': 'potential_temperature',
            'shortName': 't',
            'level': lev,
            'value': round(theta, 4),
        })

    # Wind speed at each level where both u and v exist
    u_levels = {lev for (sn, lev) in data if sn == 'u'}
    v_levels = {lev for (sn, lev) in data if sn == 'v'}
    for lev in sorted(u_levels & v_levels):
        u = data[('u', lev)][0]
        v = data[('v', lev)][0]
        ws = float(np.mean(np.sqrt(u ** 2 + v ** 2)))
        derived.append({
            'quantity': 'wind_speed',
            'shortName': 'wind',
            'level': lev,
            'value': round(ws, 4),
        })

    return derived


# ── Step 6: Validation ───────────────────────────────────────────────────────

def validate():
    # Read all harmonized message data in order
    harm_data = []
    with open(HARMONIZED_PATH, 'rb') as f:
        while True:
            mid = eccodes.codes_grib_new_from_file(f)
            if mid is None:
                break
            harm_data.append(eccodes.codes_get_values(mid))
            eccodes.codes_release(mid)

    results = []
    harm_idx = 0
    for fname in get_input_files():
        fpath = os.path.join(DATA_DIR, fname)
        max_diff = 0.0
        status = 'PASS'

        with open(fpath, 'rb') as f:
            while True:
                mid = eccodes.codes_grib_new_from_file(f)
                if mid is None:
                    break
                orig_vals = eccodes.codes_get_values(mid)
                if harm_idx < len(harm_data):
                    diff = float(np.max(np.abs(orig_vals - harm_data[harm_idx])))
                    max_diff = max(max_diff, diff)
                    if diff > 1.0:
                        status = 'FAIL'
                else:
                    status = 'FAIL'
                harm_idx += 1
                eccodes.codes_release(mid)

        results.append({
            'filename': fname,
            'status': status,
            'maxAbsDiff': round(max_diff, 6),
        })

    return results


# ── Main pipeline ─────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(SPLIT_DIR, exist_ok=True)
    os.makedirs(RULES_DIR, exist_ok=True)

    print('Step 1: Creating inventory...')
    inventory = create_inventory()
    with open(os.path.join(OUTPUT_DIR, 'inventory.json'), 'w') as f:
        json.dump(inventory, f, indent=2)
    print('  {} messages inventoried'.format(len(inventory)))

    print('Step 2: Writing grib_filter rules...')
    write_harmonize_rules()

    print('Step 3: Running harmonization via grib_filter...')
    run_harmonization()

    print('Step 4: Splitting by parameter...')
    split_by_parameter()

    print('Step 5: Computing derived quantities...')
    derived = compute_derived()
    with open(os.path.join(OUTPUT_DIR, 'derived.json'), 'w') as f:
        json.dump(derived, f, indent=2)
    print('  {} quantities computed'.format(len(derived)))

    print('Step 6: Validating...')
    validation = validate()
    with open(os.path.join(OUTPUT_DIR, 'validation.json'), 'w') as f:
        json.dump(validation, f, indent=2)
    all_pass = all(v['status'] == 'PASS' for v in validation)
    print('  Validation: {}'.format('ALL PASS' if all_pass else 'SOME FAILED'))
    print('Done.')


if __name__ == '__main__':
    main()
