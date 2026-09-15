#!/usr/bin/env python3
"""Corrected actuarial valuation engine.

Parses SOA XTbML XML files (select-and-ultimate VBT table + MP improvement
scale) and computes projected mortality rates, annuity-due values, insurance
present values, net annual premiums, and prospective net premium reserves
with interest rate stress testing.

"""

import json
import os
import xml.etree.ElementTree as ET


def find_table_file(data_dir, table_id):
    """Locate the XML file containing a given SOA table identity."""
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".xml"):
            continue
        path = os.path.join(data_dir, fname)
        tree = ET.parse(path)
        root = tree.getroot()
        tid = root.find(".//TableIdentity")
        if tid is not None and int(tid.text.strip()) == table_id:
            return path
    raise FileNotFoundError(f"Table ID {table_id} not found in {data_dir}")


def parse_select_ultimate(xml_path):
    """Parse an XTbML select-and-ultimate mortality table.

    Returns
    -------
    select : dict[int, dict[int, float]]
        select[issue_age][duration_1indexed] = qx
    ultimate : dict[int, float]
        ultimate[attained_age] = qx
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    tables = root.findall("Table")

    select = {}
    sel_values = tables[0].findall("Values/Axis")
    for age_axis in sel_values:
        age = int(age_axis.attrib["t"])
        select[age] = {}
        inner_axis = age_axis.find("Axis")
        for y_elem in inner_axis.findall("Y"):
            duration = int(y_elem.attrib["t"])
            select[age][duration] = float(y_elem.text)

    ultimate = {}
    ult_values = tables[1].findall("Values/Axis/Y")
    for y_elem in ult_values:
        age = int(y_elem.attrib["t"])
        ultimate[age] = float(y_elem.text)

    return select, ultimate


def parse_improvement_scale(xml_path):
    """Parse an XTbML mortality improvement scale (2D: age x year).

    Returns
    -------
    scale : dict[int, dict[int, float]]
        scale[age][calendar_year] = improvement_rate
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    scale = {}
    for age_axis in root.findall(".//Table/Values/Axis"):
        age = int(age_axis.attrib["t"])
        scale[age] = {}
        inner_axis = age_axis.find("Axis")
        for y_elem in inner_axis.findall("Y"):
            year = int(y_elem.attrib["t"])
            scale[age][year] = float(y_elem.text)
    return scale


def get_improvement_factor(scale, age, year, terminal_year=2037):
    """Look up improvement factor for a given age and calendar year.

    Ages outside the scale range return 0. Years beyond terminal_year
    use the terminal_year value.
    """
    if age not in scale:
        return 0.0
    age_data = scale[age]
    if year in age_data:
        return age_data[year]
    if year > terminal_year:
        return age_data.get(terminal_year, 0.0)
    return 0.0


def project_mortality_rate(q_base, scale, attained_age, calendar_year,
                           base_year=2015, terminal_year=2037):
    """Apply cumulative improvement to project a base mortality rate.

    Improvement is applied from base_year+1 through calendar_year.
    """
    cumulative = 1.0
    for t in range(base_year + 1, calendar_year + 1):
        imp = get_improvement_factor(scale, attained_age, t, terminal_year)
        cumulative *= (1.0 - imp)
    return q_base * cumulative


def lookup_base_rate(select, ultimate, issue_age, duration):
    """Look up the base mortality rate from the select-and-ultimate table.

    Uses select rates for duration <= 25 and ultimate rates for duration > 25.
    """
    if duration <= 25 and issue_age in select and duration in select[issue_age]:
        return select[issue_age][duration]
    attained_age = issue_age + duration - 1
    return ultimate[attained_age]


def compute_projected_rates(select, ultimate, scale, issue_age, start_duration,
                            num_years, start_calendar_year, base_year=2015):
    """Compute array of generationally-projected mortality rates."""
    rates = []
    for k in range(num_years):
        duration = start_duration + k
        attained_age = issue_age + duration - 1
        cal_year = start_calendar_year + k
        q_base = lookup_base_rate(select, ultimate, issue_age, duration)
        q_proj = project_mortality_rate(q_base, scale, attained_age,
                                        cal_year, base_year)
        rates.append(q_proj)
    return rates


def compute_annuity_due(projected_qx, interest_rate):
    """Compute temporary life annuity-due: sum of k_p_x * v^k."""
    v = 1.0 / (1.0 + interest_rate)
    annuity = 0.0
    kpx = 1.0
    for k, qx in enumerate(projected_qx):
        annuity += kpx * v ** k
        kpx *= (1.0 - qx)
    return annuity


def compute_insurance_pv(projected_qx, interest_rate):
    """Compute PV of term insurance: sum of k_p_x * q[k] * v^(k+1)."""
    v = 1.0 / (1.0 + interest_rate)
    insurance = 0.0
    kpx = 1.0
    for k, qx in enumerate(projected_qx):
        insurance += kpx * qx * v ** (k + 1)
        kpx *= (1.0 - qx)
    return insurance


def compute_valuation(select, ultimate, scale, val_config, base_year=2015,
                      rate_override=None):
    """Compute all valuation outputs for a single policy."""
    issue_age = val_config["issue_age"]
    issue_year = val_config["issue_year"]
    term_years = val_config["term_years"]
    interest_rate = (rate_override if rate_override is not None
                     else val_config["annual_interest_rate"])
    valuation_year = val_config["valuation_year"]
    face_amount = val_config["face_amount"]

    elapsed = valuation_year - issue_year
    remaining = term_years - elapsed

    # --- At valuation ---
    val_start_dur = elapsed + 1  # 1-indexed
    val_qx = compute_projected_rates(
        select, ultimate, scale, issue_age, val_start_dur,
        remaining, valuation_year, base_year
    )
    annuity_val = compute_annuity_due(val_qx, interest_rate)
    insurance_val = compute_insurance_pv(val_qx, interest_rate)

    # --- At issue (for net premium) ---
    issue_qx = compute_projected_rates(
        select, ultimate, scale, issue_age, 1,
        term_years, issue_year, base_year
    )
    annuity_issue = compute_annuity_due(issue_qx, interest_rate)
    insurance_issue = compute_insurance_pv(issue_qx, interest_rate)
    annual_premium = insurance_issue / annuity_issue

    # Prospective reserve per unit face
    reserve = insurance_val - annual_premium * annuity_val

    return {
        "projected_qx": val_qx,
        "annuity_due": annuity_val,
        "insurance_pv": insurance_val,
        "annual_premium": annual_premium,
        "reserve": reserve,
        "face_amount": face_amount,
    }


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    data_dir = config["data_directory"]
    base_year = config["base_year"]
    stress_bps = config["stress_bps"]

    results = {}
    total_reserve = 0.0
    total_reserve_up = 0.0
    total_reserve_down = 0.0

    for val in config["valuations"]:
        # Resolve table files by SOA table ID
        mort_path = find_table_file(data_dir, val["table_id"])
        imp_path = find_table_file(data_dir, val["improvement_table_id"])

        select, ultimate = parse_select_ultimate(mort_path)
        scale = parse_improvement_scale(imp_path)

        base_rate = val["annual_interest_rate"]

        # Base scenario
        result = compute_valuation(select, ultimate, scale, val, base_year)

        # Stress scenarios
        result_up = compute_valuation(
            select, ultimate, scale, val, base_year,
            rate_override=base_rate + stress_bps * 0.0001
        )
        result_down = compute_valuation(
            select, ultimate, scale, val, base_year,
            rate_override=base_rate - stress_bps * 0.0001
        )

        results[val["id"]] = {
            "projected_qx": result["projected_qx"],
            "annuity_due": result["annuity_due"],
            "insurance_pv": result["insurance_pv"],
            "annual_premium": result["annual_premium"],
            "reserve": result["reserve"],
            "reserve_up": result_up["reserve"],
            "reserve_down": result_down["reserve"],
        }
        total_reserve += result["face_amount"] * result["reserve"]
        total_reserve_up += result["face_amount"] * result_up["reserve"]
        total_reserve_down += result["face_amount"] * result_down["reserve"]

    results["total_reserve"] = total_reserve
    results["total_reserve_up"] = total_reserve_up
    results["total_reserve_down"] = total_reserve_down

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
