#!/usr/bin/env python3

"""Compute NAAQS design values from EPA AQS annual summary data."""
import csv
import json
import math
import os
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP


def truncate_decimals(value, decimals):
    """Truncate to specified decimal places (EPA O3 convention)."""
    multiplier = 10 ** decimals
    return math.trunc(value * multiplier) / multiplier


def round_half_up(value, decimals):
    """Round using conventional rounding (round half up), per EPA convention.
    Python's built-in round() uses banker's rounding (round half to even),
    which differs from EPA's convention at the 0.5 boundary."""
    d = Decimal(str(value))
    if decimals == 0:
        return int(d.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    fmt = Decimal('0.' + '0' * decimals)
    return float(d.quantize(fmt, rounding=ROUND_HALF_UP))


# NAAQS design value configuration for each pollutant standard.
# Each entry specifies:
#   column: which annual summary column contains the key statistic
#   aggregation: how to combine values across years (mean or max)
#   rounding: (method, decimal_places) - truncate or round
#   level: the NAAQS concentration level
#   units: display units
NAAQS_CONFIG = {
    "Ozone 8-hour 2015": {
        "column": "4th Max Value",
        "aggregation": "mean",
        "rounding": ("truncate", 3),
        "level": 0.070,
        "units": "ppm",
    },
    "PM25 Annual 2024": {
        "column": "Arithmetic Mean",
        "aggregation": "mean",
        "rounding": ("round", 1),
        "level": 9.0,
        "units": "ug/m3",
    },
    "PM25 24-hour 2024": {
        "column": "98th Percentile",
        "aggregation": "mean",
        "rounding": ("round", 0),
        "level": 35.0,
        "units": "ug/m3",
    },
    "NO2 1-hour": {
        "column": "98th Percentile",
        "aggregation": "mean",
        "rounding": ("round", 0),
        "level": 100.0,
        "units": "ppb",
    },
    "SO2 1-hour 2010": {
        "column": "99th Percentile",
        "aggregation": "mean",
        "rounding": ("round", 0),
        "level": 75.0,
        "units": "ppb",
    },
    "CO 8-hour 1971": {
        "column": "2nd Max Non Overlapping Value",
        "aggregation": "max",
        "rounding": ("round", 1),
        "level": 9.0,
        "units": "ppm",
    },
}

# Valid event types — exclude "Events Included" records
VALID_EVENT_TYPES = {"No Events", "Events Excluded", "Concurred Events Excluded"}


def compute_design_value(records, config):
    """Compute the NAAQS design value from a list of annual summary records."""
    column = config["column"]
    values = []
    for r in records:
        val = r.get(column, "").strip()
        if val == "":
            continue
        values.append(float(val))

    if not values:
        return None

    if config["aggregation"] == "mean":
        raw_dv = sum(values) / len(values)
    elif config["aggregation"] == "max":
        raw_dv = max(values)
    else:
        return None

    rounding_type, decimals = config["rounding"]
    if rounding_type == "truncate":
        return truncate_decimals(raw_dv, decimals)
    else:
        return round_half_up(raw_dv, decimals)


def main():
    data_file = "/app/data/annual_summary_2021_2023.csv"
    output_file = "/app/output/naaqs_compliance.json"

    # Read and parse the CSV
    with open(data_file, "r") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    # Filter: only use records with valid event types
    rows = [r for r in all_rows if r["Event Type"].strip() in VALID_EVENT_TYPES]

    # Group by (site_id, parameter_code, poc, pollutant_standard)
    groups = defaultdict(list)
    for r in rows:
        site_id = "{}-{}-{}".format(
            r["State Code"].strip(),
            r["County Code"].strip(),
            r["Site Num"].strip()
        )
        key = (
            site_id,
            r["Parameter Code"].strip(),
            int(r["POC"]),
            r["Pollutant Standard"].strip()
        )
        groups[key].append(r)

    # Compute design values for each monitor
    monitors = []
    for (site_id, param_code, poc, standard), records in sorted(groups.items()):
        if standard not in NAAQS_CONFIG:
            continue

        config = NAAQS_CONFIG[standard]
        dv = compute_design_value(records, config)
        if dv is None:
            continue

        # Check data completeness across all years
        data_complete = all(
            r.get("Completeness Indicator", "N").strip() == "Y"
            for r in records
        )

        # Determine compliance: DV > level means exceeds
        exceeds = dv > config["level"]

        param_name = records[0]["Parameter Name"].strip()

        monitors.append({
            "site_id": site_id,
            "parameter_code": int(param_code),
            "parameter_name": param_name,
            "poc": poc,
            "standard": standard,
            "naaqs_level": config["level"],
            "units": config["units"],
            "design_value": dv,
            "exceeds_standard": exceeds,
            "data_complete": data_complete,
        })

    # Compute site-level design values (worst-case POC per site/param/standard)
    site_groups = defaultdict(list)
    for m in monitors:
        key = (m["site_id"], m["parameter_code"], m["standard"])
        site_groups[key].append(m)

    site_level = []
    for (site_id, param_code, standard), monitor_list in sorted(site_groups.items()):
        worst = max(monitor_list, key=lambda x: x["design_value"])
        site_level.append({
            "site_id": site_id,
            "parameter_code": param_code,
            "standard": standard,
            "design_value": worst["design_value"],
            "worst_poc": worst["poc"],
            "exceeds_standard": worst["exceeds_standard"],
        })

    # Summary statistics
    exceeding = sum(1 for m in monitors if m["exceeds_standard"])
    incomplete = sum(1 for m in monitors if not m["data_complete"])

    result = {
        "assessment_period": "2021-2023",
        "monitors": monitors,
        "site_level": site_level,
        "summary": {
            "total_monitor_assessments": len(monitors),
            "exceeding": exceeding,
            "meeting": len(monitors) - exceeding,
            "incomplete_data": incomplete,
        },
    }

    os.makedirs("/app/output", exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    print("NAAQS compliance assessment written to {}".format(output_file))
    print("  Total monitors: {}".format(len(monitors)))
    print("  Exceeding: {}".format(exceeding))
    print("  Meeting: {}".format(len(monitors) - exceeding))
    print("  Incomplete data: {}".format(incomplete))


if __name__ == "__main__":
    main()
