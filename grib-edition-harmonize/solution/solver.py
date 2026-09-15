#!/usr/bin/env python3
"""GRIB conformance forensics solver — diagnoses and repairs defective GRIB files.

Reads the QC report, investigates each rejected file, applies the appropriate
correction, and produces the required audit and integrity outputs.

"""

import json
import os

import eccodes
import numpy as np

DATA_DIR = '/app/data'
OUTPUT_DIR = '/app/output'
CORRECTED_DIR = os.path.join(OUTPUT_DIR, 'corrected')

# Expected physical value ranges for common meteorological parameters (SI units)
PARAM_RANGES = {
    't':   (150.0,  350.0),     # Temperature (K)
    'r':   (0.0,    100.0),     # Relative humidity (%)
    'u':   (-150.0, 150.0),     # U-wind (m/s)
    'v':   (-150.0, 150.0),     # V-wind (m/s)
    'z':   (40000.0, 80000.0),  # Geopotential (m^2/s^2)
    'msl': (80000.0, 110000.0), # MSLP (Pa)
    'sp':  (50000.0, 110000.0), # Surface pressure (Pa)
}

# WMO standard pressure levels (hPa)
STANDARD_LEVELS = [1000, 925, 850, 700, 500, 300, 200, 100, 50, 10]


def read_messages(filepath):
    """Read all GRIB messages from a file (caller must release them)."""
    msgs = []
    with open(filepath, 'rb') as f:
        while True:
            mid = eccodes.codes_grib_new_from_file(f)
            if mid is None:
                break
            msgs.append(mid)
    return msgs


def write_messages(filepath, messages):
    """Write a list of GRIB message handles to a file."""
    for i, mid in enumerate(messages):
        mode = 'wb' if i == 0 else 'ab'
        with open(filepath, mode) as f:
            eccodes.codes_write(mid, f)


def diagnose_and_fix(filepath):
    """Analyze a GRIB file, diagnose defect, apply fix, write corrected output.

    Returns dict with filename, root_cause, correction, message_count, max_abs_diff.
    """
    filename = os.path.basename(filepath)
    messages = read_messages(filepath)
    orig_vals = [eccodes.codes_get_values(mid).copy() for mid in messages]

    # Clone all messages for modification
    fixed = [eccodes.codes_clone(mid) for mid in messages]

    diagnosis = None
    correction = None

    # ------------------------------------------------------------------
    # Diagnostic 1: Data representation — insufficient packing precision
    # ------------------------------------------------------------------
    bpv_list = [eccodes.codes_get(m, 'bitsPerValue') for m in messages]
    if any(b < 12 for b in bpv_list):
        low_bpv = min(bpv_list)
        diagnosis = (
            "Data packed with only {} bits per value, yielding unacceptable "
            "quantization error for operational NWP data".format(low_bpv)
        )
        correction = "Repacked all messages with bitsPerValue=16 for sub-unit precision"
        for i, fm in enumerate(fixed):
            eccodes.codes_set_long(fm, 'bitsPerValue', 16)
            vals = eccodes.codes_get_values(messages[i])
            eccodes.codes_set_values(fm, vals.tolist())

    # ------------------------------------------------------------------
    # Diagnostic 2: Data domain — units mismatch (check before param mismatch)
    # ------------------------------------------------------------------
    if diagnosis is None:
        for i, mid in enumerate(messages):
            sn = eccodes.codes_get(mid, 'shortName')
            vals = eccodes.codes_get_values(mid)
            vmin, vmax = float(np.min(vals)), float(np.max(vals))

            if sn not in PARAM_RANGES:
                continue
            lo, hi = PARAM_RANGES[sn]

            # Only check if values are outside expected range
            if lo <= vmin and vmax <= hi:
                continue

            # Check common unit conversion factors
            for factor in [100.0, 0.01, 1000.0, 0.001]:
                scaled_min = vmin * factor
                scaled_max = vmax * factor
                if lo * 0.8 <= scaled_min and scaled_max <= hi * 1.2:
                    diagnosis = (
                        "Values for '{}' (range {:.1f} to {:.1f}) appear to be in wrong "
                        "units — a factor of {:.0f} brings them into the expected "
                        "physical range ({:.0f} to {:.0f})".format(
                            sn, vmin, vmax, factor, lo, hi)
                    )
                    correction = "Multiplied all data values by {:.0f} to correct units".format(factor)
                    for j, fm in enumerate(fixed):
                        v = eccodes.codes_get_values(messages[j])
                        eccodes.codes_set_values(fm, (v * factor).tolist())
                    break
            if diagnosis is not None:
                break

    # ------------------------------------------------------------------
    # Diagnostic 3: Cross-section coherence — parameter vs data range
    # ------------------------------------------------------------------
    if diagnosis is None:
        for i, mid in enumerate(messages):
            sn = eccodes.codes_get(mid, 'shortName')
            vals = eccodes.codes_get_values(mid)
            vmin, vmax = float(np.min(vals)), float(np.max(vals))
            vmean = float(np.mean(vals))

            if sn not in PARAM_RANGES:
                continue
            lo, hi = PARAM_RANGES[sn]

            if lo <= vmin and vmax <= hi:
                continue

            # Find the parameter whose expected range best matches the data
            best_param = None
            best_score = float('inf')
            for param, (plo, phi) in PARAM_RANGES.items():
                if param == sn:
                    continue
                if plo * 0.5 <= vmin and vmax <= phi * 1.5:
                    range_center = (plo + phi) / 2.0
                    score = abs(vmean - range_center)
                    if score < best_score:
                        best_score = score
                        best_param = param

            if best_param is not None:
                diagnosis = (
                    "Data values (range {:.1f} to {:.1f}) are inconsistent with "
                    "declared parameter '{}'; physical domain matches '{}'".format(
                        vmin, vmax, sn, best_param)
                )
                correction = "Changed shortName from '{}' to '{}'".format(sn, best_param)
                for fm in fixed:
                    eccodes.codes_set(fm, 'shortName', best_param)
                break

    # ------------------------------------------------------------------
    # Diagnostic 4: Grid definition — scanning flag consistency
    # ------------------------------------------------------------------
    if diagnosis is None:
        j_scans = [eccodes.codes_get(m, 'jScansPositively') for m in messages]
        if len(set(j_scans)) > 1:
            diagnosis = (
                "Scanning mode flag jScansPositively is not uniform across "
                "messages in file: {}".format(j_scans)
            )
            # Determine correct value from grid coordinate ordering
            lat_first = eccodes.codes_get_double(messages[0],
                                                  'latitudeOfFirstGridPointInDegrees')
            lat_last = eccodes.codes_get_double(messages[0],
                                                 'latitudeOfLastGridPointInDegrees')
            correct_val = 0 if lat_first > lat_last else 1
            correction = (
                "Set jScansPositively={} for all messages to match "
                "grid coordinate ordering (latFirst={}, latLast={})".format(
                    correct_val, lat_first, lat_last)
            )
            for fm in fixed:
                eccodes.codes_set_long(fm, 'jScansPositively', correct_val)

    # ------------------------------------------------------------------
    # Diagnostic 5: Product definition — vertical level uniqueness
    # ------------------------------------------------------------------
    if diagnosis is None:
        by_param = {}
        for j, mid in enumerate(messages):
            sn = eccodes.codes_get(mid, 'shortName')
            lev = eccodes.codes_get(mid, 'level')
            by_param.setdefault(sn, []).append((j, lev))

        for sn, entries in by_param.items():
            levels = [lev for _, lev in entries]
            if len(levels) != len(set(levels)):
                dup_level = [l for l in levels if levels.count(l) > 1][0]
                dup_indices = [j for j, l in entries if l == dup_level]

                diagnosis = (
                    "Duplicate vertical level {} hPa for parameter '{}': "
                    "levels={}".format(dup_level, sn, levels)
                )

                # Determine correct level using data characteristics and
                # standard pressure level sequence
                means = [
                    (j, float(np.mean(eccodes.codes_get_values(messages[j]))))
                    for j in dup_indices
                ]
                means.sort(key=lambda x: x[1])

                # Next standard level below (higher pressure) the duplicate
                candidates = sorted(
                    l for l in STANDARD_LEVELS if l > dup_level
                )
                new_level = candidates[0] if candidates else dup_level + 150

                # For humidity: higher mean → lower altitude → higher pressure level
                idx_higher_mean = means[-1][0]
                eccodes.codes_set_long(fixed[idx_higher_mean], 'level', new_level)

                correction = (
                    "Reassigned message with higher data mean from level {} to "
                    "{} hPa based on physical characteristics and standard "
                    "pressure level sequence".format(dup_level, new_level)
                )
                break

    if diagnosis is None:
        diagnosis = "No defect detected"
        correction = "No correction applied"

    # Write corrected file
    out_path = os.path.join(CORRECTED_DIR, filename)
    write_messages(out_path, fixed)

    # Compute integrity (max absolute difference between orig and corrected)
    corr_vals = []
    with open(out_path, 'rb') as f:
        while True:
            mid2 = eccodes.codes_grib_new_from_file(f)
            if mid2 is None:
                break
            corr_vals.append(eccodes.codes_get_values(mid2))
            eccodes.codes_release(mid2)

    max_diff = 0.0
    for ov, cv in zip(orig_vals, corr_vals):
        diff = float(np.max(np.abs(ov - cv)))
        max_diff = max(max_diff, diff)

    # Cleanup handles
    for mid in messages:
        eccodes.codes_release(mid)
    for fm in fixed:
        eccodes.codes_release(fm)

    return {
        'filename': filename,
        'root_cause': diagnosis,
        'correction': correction,
        'message_count': len(orig_vals),
        'max_abs_diff': round(max_diff, 6),
    }


def main():
    os.makedirs(CORRECTED_DIR, exist_ok=True)

    # Read QC report for context
    qc_path = '/app/qc_report.log'
    if os.path.exists(qc_path):
        with open(qc_path) as f:
            print("=== QC Report ===")
            print(f.read())

    audit = []
    integrity = {}

    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith('.grib'):
            continue
        filepath = os.path.join(DATA_DIR, fname)
        print("Processing {}...".format(fname))

        result = diagnose_and_fix(filepath)

        audit.append({
            'filename': result['filename'],
            'root_cause': result['root_cause'],
            'correction': result['correction'],
        })
        integrity[result['filename']] = {
            'message_count': result['message_count'],
            'max_abs_diff': result['max_abs_diff'],
        }

        print("  Diagnosis: {}".format(result['root_cause'][:100]))
        print("  Correction: {}".format(result['correction'][:100]))
        print("  Max abs diff: {}".format(result['max_abs_diff']))
        print()

    # Write outputs
    with open(os.path.join(OUTPUT_DIR, 'audit.json'), 'w') as f:
        json.dump(audit, f, indent=2)
    with open(os.path.join(OUTPUT_DIR, 'integrity.json'), 'w') as f:
        json.dump(integrity, f, indent=2)

    print("Done. {} files processed.".format(len(audit)))


if __name__ == '__main__':
    main()
