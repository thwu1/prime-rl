#!/usr/bin/env python3
"""
Compute correct NAAQS design values from SQLite database, using the
pipe-delimited standards reference for standard definitions, XML monitor
registry for method designation filtering, and compare against previous
per-state reports extracted from tar.gz archive.

"""
import csv
import json
import math
import os
import sqlite3
import tarfile
import xml.etree.ElementTree as ET

DB_PATH = "/app/monitoring.db"
ARCHIVE_PATH = "/app/audit/state_reports.tar.gz"
PSV_PATH = "/app/data/naaqs_standards.psv"
XML_PATH = "/app/data/monitor_config.xml"
OUTPUT_REPORT = "/app/output/compliance_report.json"
OUTPUT_ERRORS = "/app/output/error_analysis.json"

# Mapping from statistical form descriptions to AQS database column names.
# The PSV file describes each standard's form conceptually (e.g., "3-yr avg
# of annual 4th highest daily max"). The solver must understand these
# statistical concepts and discover the corresponding columns in the
# undocumented database schema through exploration.
STAT_FORM_TO_COLUMN = {
    "3-yr avg of annual 4th highest daily max": "fourth_max_value",
    "3-yr avg of annual arithmetic mean": "arithmetic_mean",
    "3-yr avg of annual 98th percentile": "pct_98th",
    "3-yr avg of annual 99th percentile": "pct_99th",
    "3-yr avg of annual exceedance count": "primary_exceedance_count",
}


def round_half_up(x, decimals=0):
    """EPA conventional rounding: 0.5 rounds up."""
    multiplier = 10 ** decimals
    return math.floor(x * multiplier + 0.5) / multiplier


def apply_rounding(value, method):
    if method == "truncate_3dp":
        return math.trunc(value * 1000) / 1000
    elif method == "round_1dp":
        return round_half_up(value, 1)
    elif method == "round_int":
        return round_half_up(value, 0)
    elif method == "none":
        return value
    else:
        raise ValueError(f"Unknown rounding method: {method}")


def load_valid_monitors_from_xml():
    """Parse XML monitor registry to identify FRM/FEM monitors eligible
    for NAAQS compliance determination.

    Returns a set of (state_code, county_code, site_num, parameter_code)
    tuples for monitors with FRM or FEM method designation that are
    currently active.
    """
    ns = {
        'aqs': 'http://www.epa.gov/aqs/monitoring/2.0',
        'geo': 'http://www.epa.gov/aqs/geo/1.0',
    }
    tree = ET.parse(XML_PATH)
    root = tree.getroot()

    valid = set()
    for site in root.findall('.//aqs:MonitoringSite', ns):
        state = site.get('stateCode')
        county = site.get('countyCode')
        site_num = site.get('siteNumber')
        for monitor in site.findall('aqs:Monitor', ns):
            param = monitor.get('parameterCode')
            poc = monitor.get('poc')
            method_elem = monitor.find('aqs:MethodDesignation', ns)
            status_elem = monitor.find('aqs:OperationalStatus', ns)

            method = method_elem.text if method_elem is not None else ''
            active = (status_elem.get('active') == 'true') if status_elem is not None else False

            # Only FRM/FEM monitors with POC 1 are used for regulatory compliance
            if method in ('FRM', 'FEM') and active and poc == '1':
                valid.add((state, county, site_num, int(param)))

    return valid


def load_naaqs_standards():
    """Parse pipe-delimited NAAQS standards reference file.

    The PSV no longer includes explicit database column mappings.
    We map the statistical_form description to the corresponding DB column
    using domain knowledge of AQS data structure.

    Returns:
        naaqs: dict mapping (param_code, poll_std) to config
        current_standards: dict mapping param_code to list of current standard names
    """
    naaqs = {}
    current_standards = {}

    with open(PSV_PATH) as f:
        reader = csv.DictReader(f, delimiter='|')
        for row in reader:
            if row['superseded_by'].strip():
                continue  # skip superseded standards

            pc = int(row['parameter_code'])
            ps = row['pollutant_standard']

            # Map statistical form description to database column
            stat_form = row['statistical_form']
            stat_col = STAT_FORM_TO_COLUMN.get(stat_form)
            if stat_col is None:
                raise ValueError(
                    f"Cannot map statistical form '{stat_form}' to database column. "
                    f"Explore the database schema to find the appropriate column."
                )

            # PM10 uses exceedance count form
            if row['compliance_method'] == 'exceedance_count_le_1':
                output_naaqs = 1.0
                output_units = "Expected exceedances per year"
            else:
                output_naaqs = float(row['naaqs_level'])
                output_units = row['naaqs_units']

            naaqs[(pc, ps)] = {
                "naaqs_level": output_naaqs,
                "units": output_units,
                "statistic": stat_col,
                "rounding": row['decimal_reporting'],
            }
            current_standards.setdefault(pc, []).append(ps)

    return naaqs, current_standards


def load_previous_reports():
    """Extract and merge per-state previous reports from tar.gz archive."""
    all_monitors = []
    with tarfile.open(ARCHIVE_PATH, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name.endswith('.json'):
                f = tar.extractfile(member)
                if f:
                    data = json.load(f)
                    all_monitors.extend(data.get("monitors", []))
    return all_monitors


def make_site_id(state_code, county_code, site_num):
    return f"{state_code}-{county_code}-{site_num}"


def query_data(valid_monitors):
    """Query all relevant data from SQLite database, filtered to valid monitors."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            m.state_code, m.county_code, m.site_num,
            m.parameter_code, m.poc, m.parameter_name,
            d.pollutant_standard, d.year,
            d.event_type, d.completeness_indicator,
            d.arithmetic_mean, d.fourth_max_value,
            d.pct_99th, d.pct_98th,
            d.primary_exceedance_count
        FROM monitors m
        JOIN annual_data d ON m.monitor_id = d.monitor_id
        WHERE m.poc = 1
          AND d.event_type IN ('No Events', 'Events Included')
        ORDER BY m.state_code, m.county_code, m.site_num,
                 m.parameter_code, d.pollutant_standard, d.year
    """)

    rows = cursor.fetchall()
    conn.close()

    # Filter to only monitors validated as FRM/FEM via XML registry
    filtered = [
        r for r in rows
        if (r["state_code"], r["county_code"], r["site_num"], r["parameter_code"])
        in valid_monitors
    ]

    return filtered


def compute_design_values():
    """Compute 3-year design values for all eligible monitors."""
    valid_monitors = load_valid_monitors_from_xml()
    naaqs, current_stds = load_naaqs_standards()
    rows = query_data(valid_monitors)

    # Group by (site_id, parameter_code, pollutant_standard)
    groups = {}
    for row in rows:
        site_id = make_site_id(row["state_code"], row["county_code"], row["site_num"])
        key = (site_id, row["parameter_code"], row["parameter_name"], row["pollutant_standard"])
        if key not in groups:
            groups[key] = []
        groups[key].append(dict(row))

    results = []
    for (site_id, param_code, param_name, poll_std), records in groups.items():
        # Filter to current standards only
        current = current_stds.get(param_code, [])
        if poll_std not in current:
            continue

        naaqs_key = (param_code, poll_std)
        if naaqs_key not in naaqs:
            continue

        config = naaqs[naaqs_key]
        stat_col = config["statistic"]

        # Check all 3 years have complete data
        complete_years = {r["year"] for r in records if r["completeness_indicator"] == "Y"}
        required_years = {2022, 2023, 2024}

        if not required_years.issubset(complete_years):
            results.append({
                "site_id": site_id,
                "parameter_code": int(param_code),
                "parameter_name": param_name,
                "pollutant_standard": poll_std,
                "design_value": None,
                "naaqs_level": config["naaqs_level"],
                "units": config["units"],
                "status": "Insufficient Data",
            })
            continue

        # Get complete records only, extract annual statistic values
        annual_values = []
        for year in [2022, 2023, 2024]:
            year_records = [r for r in records if r["year"] == year and r["completeness_indicator"] == "Y"]
            if not year_records:
                break
            val = float(year_records[0][stat_col])
            annual_values.append(val)

        if len(annual_values) != 3:
            results.append({
                "site_id": site_id,
                "parameter_code": int(param_code),
                "parameter_name": param_name,
                "pollutant_standard": poll_std,
                "design_value": None,
                "naaqs_level": config["naaqs_level"],
                "units": config["units"],
                "status": "Insufficient Data",
            })
            continue

        # Compute 3-year design value
        raw_dv = sum(annual_values) / 3.0
        design_value = apply_rounding(raw_dv, config["rounding"])

        # Determine compliance
        status = "Meeting" if design_value <= config["naaqs_level"] else "Exceeding"

        results.append({
            "site_id": site_id,
            "parameter_code": int(param_code),
            "parameter_name": param_name,
            "pollutant_standard": poll_std,
            "design_value": design_value,
            "naaqs_level": config["naaqs_level"],
            "units": config["units"],
            "status": status,
        })

    # Sort
    results.sort(key=lambda x: (x["site_id"], x["parameter_code"], x["pollutant_standard"]))
    return results


def find_errors(correct_report, prev_monitors):
    """Compare correct report to previous per-state reports and identify errors."""
    errors = []

    # Build lookups
    correct_lookup = {}
    for entry in correct_report:
        key = (entry["site_id"], entry["parameter_code"], entry["pollutant_standard"])
        correct_lookup[key] = entry

    prev_lookup = {}
    for entry in prev_monitors:
        key = (entry["site_id"], entry["parameter_code"], entry["pollutant_standard"])
        prev_lookup[key] = entry

    # Check for entries in previous report using superseded standards
    correct_stds = {e["pollutant_standard"] for e in correct_report}

    for pe in prev_monitors:
        if pe["pollutant_standard"] not in correct_stds:
            # Find correct standard for same site/param
            correct_std_name = None
            for ce in correct_report:
                if (ce["site_id"] == pe["site_id"] and
                    ce["parameter_code"] == pe["parameter_code"] and
                    ce["pollutant_standard"] != pe["pollutant_standard"]):
                    if "Annual" in pe["pollutant_standard"] and "Annual" in ce["pollutant_standard"]:
                        correct_std_name = ce["pollutant_standard"]
                        break
            errors.append({
                "affected_monitor": pe["site_id"],
                "parameter_code": pe["parameter_code"],
                "error_category": "superseded_standard",
                "previous_value": pe["pollutant_standard"],
                "corrected_value": correct_std_name or "PM25 Annual 2024",
                "explanation": (
                    f"Previous report used superseded standard '{pe['pollutant_standard']}' "
                    f"(NAAQS level {pe['naaqs_level']}). The current standard is "
                    f"'{correct_std_name or 'PM25 Annual 2024'}' with a lower NAAQS level. "
                    f"This affected the compliance determination."
                ),
            })

    # Check remaining entries with matching standards
    for key, ce in correct_lookup.items():
        pe = prev_lookup.get(key)
        if pe is None:
            continue

        # Check design value
        if ce["design_value"] is not None and pe["design_value"] is not None:
            if abs(ce["design_value"] - pe["design_value"]) > 0.001:
                if ce["parameter_code"] == 44201:
                    explanation = (
                        f"Ozone design value should be truncated to 3 decimal places, not rounded. "
                        f"Previous value {pe['design_value']} was computed using rounding; "
                        f"correct truncated value is {ce['design_value']}."
                    )
                elif ce["parameter_code"] == 42401:
                    explanation = (
                        f"SO2 design value must use the 99th percentile of daily maximum "
                        f"concentrations, not the 98th percentile. Previous value {pe['design_value']} "
                        f"was derived from the 98th percentile; correct 99th percentile-based "
                        f"value is {ce['design_value']}."
                    )
                else:
                    explanation = (
                        f"Design value mismatch: previous={pe['design_value']}, "
                        f"correct={ce['design_value']}."
                    )
                errors.append({
                    "affected_monitor": ce["site_id"],
                    "parameter_code": ce["parameter_code"],
                    "error_category": "design_value_computation",
                    "previous_value": pe["design_value"],
                    "corrected_value": ce["design_value"],
                    "explanation": explanation,
                })

        # Check status
        if ce["status"] != pe["status"]:
            if ce["status"] == "Insufficient Data":
                explanation = (
                    f"Monitor {ce['site_id']} has incomplete data for at least one year "
                    f"(completeness indicator = 'N'). The design value cannot be validly "
                    f"computed. Previous report incorrectly computed a value of "
                    f"{pe['design_value']} without checking data completeness."
                )
            else:
                explanation = (
                    f"Compliance status changed from '{pe['status']}' to '{ce['status']}'. "
                )
            errors.append({
                "affected_monitor": ce["site_id"],
                "parameter_code": ce["parameter_code"],
                "error_category": "compliance_status",
                "previous_value": pe["status"],
                "corrected_value": ce["status"],
                "explanation": explanation,
            })

        # Check naaqs_level
        if abs(ce["naaqs_level"] - pe["naaqs_level"]) > 0.01:
            if ce["parameter_code"] == 81102:
                explanation = (
                    f"PM10 compliance is determined by expected exceedance count (threshold = 1), "
                    f"not by comparing a concentration to 150 ug/m3. Previous report used "
                    f"naaqs_level={pe['naaqs_level']} (the concentration standard); correct "
                    f"comparison threshold is {ce['naaqs_level']} expected exceedances per year."
                )
            else:
                explanation = (
                    f"NAAQS level mismatch: previous={pe['naaqs_level']}, "
                    f"correct={ce['naaqs_level']}."
                )
            errors.append({
                "affected_monitor": ce["site_id"],
                "parameter_code": ce["parameter_code"],
                "error_category": "naaqs_level",
                "previous_value": pe["naaqs_level"],
                "corrected_value": ce["naaqs_level"],
                "explanation": explanation,
            })

    return errors


def main():
    os.makedirs(os.path.dirname(OUTPUT_REPORT), exist_ok=True)

    # Compute correct design values
    results = compute_design_values()

    # Write corrected compliance report
    with open(OUTPUT_REPORT, "w") as f:
        json.dump({"monitors": results}, f, indent=2)
    print(f"Wrote {len(results)} monitor evaluations to {OUTPUT_REPORT}")

    # Load and merge previous per-state reports
    prev_monitors = load_previous_reports()
    print(f"Loaded {len(prev_monitors)} monitors from state report archive")

    # Find errors in previous reports
    errors = find_errors(results, prev_monitors)

    # Write error analysis
    with open(OUTPUT_ERRORS, "w") as f:
        json.dump({"errors": errors}, f, indent=2)
    print(f"Identified {len(errors)} errors, wrote to {OUTPUT_ERRORS}")

    # Summary
    for r in results:
        dv = r["design_value"]
        dv_str = f"{dv}" if dv is not None else "N/A"
        print(f"  {r['site_id']} | {r['pollutant_standard']:25s} | DV={dv_str:>8s} | {r['status']}")


if __name__ == "__main__":
    main()
