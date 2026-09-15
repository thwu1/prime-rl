#!/usr/bin/env python3
"""Actuarial valuation pipeline — legacy implementation.

Reads config.json, parses XTbML mortality/improvement data, and computes
net premium reserves for a portfolio of term life insurance policies.
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


def load_mortality_table(xml_path):
    """Parse a select-and-ultimate XTbML mortality table."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    tables = root.findall("Table")

    select = {}
    ultimate = {}

    if len(tables) >= 2:
        for age_axis in tables[0].findall("Values/Axis"):
            age = int(age_axis.attrib["t"])
            select[age] = {}
            inner = age_axis.find("Axis")
            for y in inner.findall("Y"):
                dur = int(y.attrib["t"])
                select[age][dur] = float(y.text)

        for y in tables[1].findall("Values/Axis/Y"):
            age = int(y.attrib["t"])
            ultimate[age] = float(y.text)
    else:
        for y in tables[0].findall("Values/Axis/Y"):
            age = int(y.attrib["t"])
            ultimate[age] = float(y.text)

    return select, ultimate


def load_improvement_scale(xml_path):
    """Parse an MP improvement-scale XTbML file (age x year)."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    scale = {}
    for age_axis in root.findall(".//Table/Values/Axis"):
        age = int(age_axis.attrib["t"])
        scale[age] = {}
        inner = age_axis.find("Axis")
        for y in inner.findall("Y"):
            yr = int(y.attrib["t"])
            scale[age][yr] = float(y.text)
    return scale


def improvement_factor(scale, age, year):
    """Return the improvement factor for a given age and calendar year."""
    if age not in scale:
        return 0.0
    age_data = scale[age]
    if year in age_data:
        return age_data[year]
    if year > 2037:
        return age_data.get(2037, 0.0)
    return 0.0


def project_rate(q_base, scale, attained_age, calendar_year, base_year):
    """Project a base mortality rate using cumulative improvement factors."""
    cumulative = 1.0
    for t in range(base_year, calendar_year + 1):
        imp = improvement_factor(scale, attained_age, t)
        cumulative *= (1.0 - imp)
    return q_base * cumulative


def lookup_base_rate(select, ultimate, issue_age, duration):
    """Retrieve base mortality rate from the select or ultimate table."""
    if duration < 25 and issue_age in select and duration in select[issue_age]:
        return select[issue_age][duration]
    attained_age = issue_age + duration - 1
    return ultimate[attained_age]


def projected_rates_array(select, ultimate, scale, issue_age, start_dur,
                          count, start_year, base_year):
    """Build an array of projected mortality rates."""
    rates = []
    for k in range(count):
        dur = start_dur + k
        att_age = issue_age + dur - 1
        cal_yr = start_year + k
        qb = lookup_base_rate(select, ultimate, issue_age, dur)
        rates.append(project_rate(qb, scale, att_age, cal_yr, base_year))
    return rates


def temporary_annuity(proj_qx, interest_rate):
    """Compute temporary life annuity value."""
    v = 1.0 / (1.0 + interest_rate)
    result = 0.0
    kpx = 1.0
    for k, qx in enumerate(proj_qx):
        result += kpx * v ** (k + 1)
        kpx *= (1.0 - qx)
    return result


def term_insurance_pv(proj_qx, interest_rate):
    """Compute present value of term life insurance benefits."""
    v = 1.0 / (1.0 + interest_rate)
    result = 0.0
    kpx = 1.0
    for k, qx in enumerate(proj_qx):
        result += kpx * qx * v ** (k + 1)
        kpx *= (1.0 - qx)
    return result


def run_valuation(select, ultimate, scale, val_cfg, base_year):
    """Compute valuation outputs for a single policy."""
    ia = val_cfg["issue_age"]
    iy = val_cfg["issue_year"]
    term = val_cfg["term_years"]
    rate = val_cfg["annual_interest_rate"]
    vy = val_cfg["valuation_year"]
    fa = val_cfg["face_amount"]

    elapsed = vy - iy
    remaining = term - elapsed

    # Rates from valuation date
    val_qx = projected_rates_array(
        select, ultimate, scale, ia, elapsed + 1, remaining, vy, base_year
    )
    ann_val = temporary_annuity(val_qx, rate)
    ins_val = term_insurance_pv(val_qx, rate)

    # Rates from issue date (for premium calculation)
    issue_qx = projected_rates_array(
        select, ultimate, scale, ia, 1, term, iy, base_year
    )
    ann_issue = temporary_annuity(issue_qx, rate)
    ins_issue = term_insurance_pv(issue_qx, rate)

    premium = ins_issue / ann_issue
    reserve = ins_val - premium * ann_val

    return {
        "projected_qx": val_qx,
        "annuity_due": ann_val,
        "insurance_pv": ins_val,
        "annual_premium": premium,
        "reserve": reserve,
        "face_amount": fa,
    }


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    data_dir = config["data_directory"]
    base_year = config["base_year"]

    results = {}
    total_reserve = 0.0

    for val in config["valuations"]:
        mort_path = find_table_file(data_dir, val["table_id"])
        imp_path = find_table_file(data_dir, val["improvement_table_id"])

        select, ultimate = load_mortality_table(mort_path)
        scale = load_improvement_scale(imp_path)

        out = run_valuation(select, ultimate, scale, val, base_year)
        results[val["id"]] = {
            "projected_qx": out["projected_qx"],
            "annuity_due": out["annuity_due"],
            "insurance_pv": out["insurance_pv"],
            "annual_premium": out["annual_premium"],
            "reserve": out["reserve"],
        }
        total_reserve += out["face_amount"] * out["reserve"]

    results["total_reserve"] = total_reserve

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
