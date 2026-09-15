#!/usr/bin/env python3

"""TY2025 Federal Income Tax Computation Engine."""

import json
import os
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# TY2025 Constants (derived from IRS reference documents)
# ---------------------------------------------------------------------------

STANDARD_DEDUCTION = {
    "single": 15750, "mfj": 31500, "mfs": 15750,
    "hoh": 23625, "qss": 31500,
}

TAX_BRACKETS = {
    "single": [
        (0, 11925, 0.10), (11925, 48475, 0.12), (48475, 103350, 0.22),
        (103350, 197300, 0.24), (197300, 250525, 0.32),
        (250525, 626350, 0.35), (626350, None, 0.37),
    ],
    "mfj": [
        (0, 23850, 0.10), (23850, 96950, 0.12), (96950, 206700, 0.22),
        (206700, 394600, 0.24), (394600, 501050, 0.32),
        (501050, 751600, 0.35), (751600, None, 0.37),
    ],
    "mfs": [
        (0, 11925, 0.10), (11925, 48475, 0.12), (48475, 103350, 0.22),
        (103350, 197300, 0.24), (197300, 250525, 0.32),
        (250525, 375800, 0.35), (375800, None, 0.37),
    ],
    "hoh": [
        (0, 17000, 0.10), (17000, 64850, 0.12), (64850, 103350, 0.22),
        (103350, 197300, 0.24), (197300, 250500, 0.32),
        (250500, 626350, 0.35), (626350, None, 0.37),
    ],
    "qss": [
        (0, 23850, 0.10), (23850, 96950, 0.12), (96950, 206700, 0.22),
        (206700, 394600, 0.24), (394600, 501050, 0.32),
        (501050, 751600, 0.35), (751600, None, 0.37),
    ],
}

CG_BREAKPOINTS = {
    "single": (48350, 533400),
    "mfj": (96700, 600050),
    "mfs": (48350, 300000),
    "hoh": (64750, 566700),
    "qss": (96700, 600050),
}

SS_RATE = 0.124
MEDICARE_RATE = 0.029
ADDITIONAL_MEDICARE_RATE = 0.009

CREDIT_RATE = 0.30
CATEGORY_CAPS = {
    "insulation": 1200, "door": 500, "windows": 600,
    "central_ac": 600, "water_heater": 600, "furnace_boiler": 600,
    "electrical_panel": 600, "home_energy_audit": 150,
}
NON_HP_AGG_CAP = 1200
HP_AGG_CAP = 2000

# ---------------------------------------------------------------------------
# XML Constants
# ---------------------------------------------------------------------------

MEF_NS = "urn:irs:form1040:ty2025"

FORM_1040_XML_LINES = [
    "Line1a", "Line1z", "Line3a", "Line3b", "Line7",
    "Line9", "Line11a", "Line12e", "Line15", "Line16",
    "Line18", "Line20", "Line22", "Line23", "Line24",
    "Line25a", "Line25d", "Line33", "Line34", "Line37",
]

FORM_5695_XML_LINES = [
    "Line18b", "Line19h", "Line20d", "Line22d", "Line23d",
    "Line24d", "Line25e", "Line26c", "Line27", "Line28",
    "Line29h", "Line30", "Line31", "Line32",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def irs_round(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bracket_tax(taxable_income, brackets):
    tax = 0.0
    for lower, upper, rate in brackets:
        if upper is None:
            upper = float("inf")
        if taxable_income <= lower:
            break
        tax += (min(taxable_income, upper) - lower) * rate
    return tax


def compute_schedule_d(scenario):
    cg = scenario.get("capital_gains", {})
    st = cg.get("short_term", 0)
    lt = cg.get("long_term", 0)
    return {"line_7": st, "line_15": lt, "line_16": st + lt}


def compute_schedule_h(scenario):
    sh = scenario.get("schedule_h", {})
    r = {f"line_{i}": 0 for i in range(1, 9)}
    if not sh.get("has_household_employees", False):
        return r
    r["line_1"] = sh["total_cash_wages_ss"]
    r["line_2"] = irs_round(r["line_1"] * SS_RATE)
    r["line_3"] = sh["total_cash_wages_medicare"]
    r["line_4"] = irs_round(r["line_3"] * MEDICARE_RATE)
    r["line_5"] = sh.get("total_cash_wages_additional_medicare", 0)
    r["line_6"] = irs_round(r["line_5"] * ADDITIONAL_MEDICARE_RATE)
    r["line_7"] = sh.get("federal_income_tax_withheld", 0)
    r["line_8"] = r["line_2"] + r["line_4"] + r["line_6"] + r["line_7"]
    return r


def compute_form_5695(scenario, tax_line_18):
    f = scenario.get("form_5695", {})
    r = {"line_18b": 0, "line_19h": 0, "line_20d": 0,
         "line_22d": 0, "line_23d": 0, "line_24d": 0,
         "line_25e": 0, "line_26c": 0,
         "line_27": 0, "line_28": 0,
         "line_29h": 0, "line_30": 0, "line_31": 0, "line_32": 0}

    mapping = [
        ("insulation_cost", "insulation", "line_18b"),
        ("door_cost", "door", "line_19h"),
        ("window_cost", "windows", "line_20d"),
        ("central_ac_cost", "central_ac", "line_22d"),
        ("water_heater_cost", "water_heater", "line_23d"),
        ("furnace_boiler_cost", "furnace_boiler", "line_24d"),
        ("electrical_panel_cost", "electrical_panel", "line_25e"),
        ("home_energy_audit_cost", "home_energy_audit", "line_26c"),
    ]
    for cost_key, cap_key, line_key in mapping:
        cost = f.get(cost_key, 0)
        r[line_key] = min(irs_round(cost * CREDIT_RATE), CATEGORY_CAPS[cap_key])

    r["line_27"] = sum(r[m[2]] for m in mapping)
    r["line_28"] = min(r["line_27"], NON_HP_AGG_CAP)

    hp_total = (f.get("heat_pump_cost", 0) +
                f.get("heat_pump_water_heater_cost", 0) +
                f.get("biomass_stove_cost", 0))
    r["line_29h"] = min(irs_round(hp_total * CREDIT_RATE), HP_AGG_CAP)

    r["line_30"] = r["line_28"] + r["line_29h"]
    r["line_31"] = max(tax_line_18, 0)
    r["line_32"] = min(r["line_30"], r["line_31"])
    return r


def compute_qdcgtw(taxable_income, qual_div, sd15, sd16, brackets, fs):
    zero_lim, fifteen_lim = CG_BREAKPOINTS[fs]

    w1 = taxable_income
    w2 = qual_div
    w3 = max(min(sd15, sd16), 0) if sd15 is not None and sd16 is not None else 0
    w4 = w2 + w3
    w5 = max(w1 - w4, 0)

    w7 = min(w1, zero_lim)
    w8 = min(w5, w7)
    w9 = w7 - w8

    w10 = min(w1, w4)
    w12 = w10 - w9

    w14 = min(w1, fifteen_lim)
    w15 = w5 + w9
    w16 = max(w14 - w15, 0)
    w17 = min(w12, w16)
    w18 = irs_round(w17 * 0.15)

    w19 = w9 + w17
    w20 = w10 - w19
    w21 = irs_round(w20 * 0.20)

    w22 = irs_round(bracket_tax(w5, brackets))
    w23 = w18 + w21 + w22
    w24 = irs_round(bracket_tax(w1, brackets))
    return min(w23, w24)


def compute_return(scenario):
    fs = scenario["filing_status"]
    brackets = TAX_BRACKETS[fs]
    std_ded = STANDARD_DEDUCTION[fs]

    total_wages = sum(w["wages"] for w in scenario["w2s"])
    total_fit = sum(w["federal_tax_withheld"] for w in scenario["w2s"])
    qual_div = scenario.get("dividends", {}).get("qualified", 0)
    ord_div = scenario.get("dividends", {}).get("ordinary", 0)
    stcg = scenario.get("capital_gains", {}).get("short_term", 0)
    ltcg = scenario.get("capital_gains", {}).get("long_term", 0)
    has_cg = (stcg != 0 or ltcg != 0)

    sd = compute_schedule_d(scenario)

    f = {}
    f["line_1a"] = total_wages
    f["line_1z"] = total_wages
    f["line_2b"] = 0
    f["line_3a"] = qual_div
    f["line_3b"] = ord_div
    f["line_7"] = sd["line_16"] if has_cg else 0
    f["line_9"] = f["line_1z"] + f["line_2b"] + f["line_3b"] + f["line_7"]
    f["line_10"] = 0
    f["line_11a"] = f["line_9"] - f["line_10"]
    f["line_12e"] = std_ded
    f["line_14"] = f["line_12e"]
    f["line_15"] = max(f["line_11a"] - f["line_14"], 0)

    use_qdcgtw = (qual_div > 0 or
                  (has_cg and sd["line_15"] > 0 and sd["line_16"] > 0))

    if use_qdcgtw and f["line_15"] > 0:
        f["line_16"] = compute_qdcgtw(
            f["line_15"], qual_div,
            sd["line_15"] if has_cg else None,
            sd["line_16"] if has_cg else None,
            brackets, fs)
    else:
        f["line_16"] = irs_round(bracket_tax(f["line_15"], brackets))

    f["line_17"] = 0
    f["line_18"] = f["line_16"] + f["line_17"]

    f5695 = compute_form_5695(scenario, f["line_18"])
    s3 = {"line_5b": f5695["line_32"], "line_8": f5695["line_32"]}
    sh = compute_schedule_h(scenario)
    s2 = {"line_3": 0, "line_9": sh["line_8"], "line_21": sh["line_8"]}

    f["line_19"] = 0
    f["line_20"] = s3["line_8"]
    f["line_21"] = f["line_19"] + f["line_20"]
    f["line_22"] = max(f["line_18"] - f["line_21"], 0)
    f["line_23"] = s2["line_21"]
    f["line_24"] = f["line_22"] + f["line_23"]
    f["line_25a"] = total_fit
    f["line_25d"] = f["line_25a"]
    f["line_33"] = f["line_25d"]

    if f["line_33"] > f["line_24"]:
        f["line_34"] = f["line_33"] - f["line_24"]
        f["line_37"] = 0
    else:
        f["line_34"] = 0
        f["line_37"] = f["line_24"] - f["line_33"]

    return {
        "form_1040": f, "schedule_d": sd, "schedule_h": sh,
        "form_5695": f5695, "schedule_2": s2, "schedule_3": s3,
    }


# ---------------------------------------------------------------------------
# XML Generation
# ---------------------------------------------------------------------------

def xml_key_to_json(xml_tag):
    """Convert XML element name to JSON key. E.g., Line1a -> line_1a"""
    return "line_" + xml_tag[4:].lower()


def generate_xml(scenario, result, output_path):
    """Generate MeF-compatible XML return validated against mef_schema.xsd."""
    ET.register_namespace("", MEF_NS)

    def se(parent, tag, text=None):
        e = ET.SubElement(parent, f"{{{MEF_NS}}}{tag}")
        if text is not None:
            e.text = str(text)
        return e

    root = ET.Element(f"{{{MEF_NS}}}TaxReturn")

    # Header
    header = se(root, "Header")
    se(header, "FilingStatus", scenario["filing_status"])
    se(header, "TaxYear", 2025)

    # Form 1040
    f1040 = se(root, "Form1040")
    for tag in FORM_1040_XML_LINES:
        key = xml_key_to_json(tag)
        se(f1040, tag, result["form_1040"][key])

    # Schedule D
    sched_d = se(root, "ScheduleD")
    for tag in ["Line7", "Line15", "Line16"]:
        key = xml_key_to_json(tag)
        se(sched_d, tag, result["schedule_d"][key])

    # Schedule H
    sched_h = se(root, "ScheduleH")
    for i in range(1, 9):
        se(sched_h, f"Line{i}", result["schedule_h"][f"line_{i}"])

    # Form 5695
    f5695 = se(root, "Form5695")
    for tag in FORM_5695_XML_LINES:
        key = xml_key_to_json(tag)
        se(f5695, tag, result["form_5695"][key])

    # Schedule 2
    sched_2 = se(root, "Schedule2")
    se(sched_2, "Line9", result["schedule_2"]["line_9"])
    se(sched_2, "Line21", result["schedule_2"]["line_21"])

    # Schedule 3
    sched_3 = se(root, "Schedule3")
    se(sched_3, "Line5b", result["schedule_3"]["line_5b"])
    se(sched_3, "Line8", result["schedule_3"]["line_8"])

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(output_path, xml_declaration=True, encoding="UTF-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    scenarios_dir = "/app/scenarios"
    results_dir = "/app/results"
    xml_dir = "/app/xml_returns"
    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(xml_dir, exist_ok=True)

    for fn in sorted(os.listdir(scenarios_dir)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(scenarios_dir, fn)) as fp:
            scenario = json.load(fp)
        result = compute_return(scenario)

        # Write JSON result
        with open(os.path.join(results_dir, fn), "w") as out:
            json.dump(result, out, indent=2)
            out.write("\n")

        # Write XML return
        name = fn.replace(".json", "")
        generate_xml(scenario, result, os.path.join(xml_dir, f"{name}.xml"))


if __name__ == "__main__":
    main()
