#!/usr/bin/env python3
"""
Pharmacokinetic analysis engine.
Parses DrugBank XML, extracts free-text half-life values,
computes one-compartment PK parameters, and assesses therapeutic status.
"""


import json
import math
import os
import re
import xml.etree.ElementTree as ET


NS = {'db': 'http://www.drugbank.ca'}


# ═══════════════════════════════════════════
# DrugBank XML parser
# ═══════════════════════════════════════════

def parse_drugbank_xml(filepath):
    """Parse DrugBank XML and extract drug data."""
    tree = ET.parse(filepath)
    root = tree.getroot()
    drugs = []

    for drug_elem in root.findall('db:drug', NS):
        # Get primary drugbank-id
        did = None
        for id_elem in drug_elem.findall('db:drugbank-id', NS):
            if id_elem.get('primary') == 'true':
                did = id_elem.text
                break
        if did is None:
            id_elem = drug_elem.find('db:drugbank-id', NS)
            if id_elem is not None:
                did = id_elem.text

        name = drug_elem.findtext('db:name', default='', namespaces=NS)
        half_life_text = drug_elem.findtext('db:half-life', default='', namespaces=NS)

        # Extract structured PK parameters
        pk_elem = drug_elem.find('db:pharmacokinetic-parameters', NS)
        vd_per_kg = 0.0
        pb_frac = 0.0
        t_min = 0.0
        t_max = 0.0

        if pk_elem is not None:
            vd_text = pk_elem.findtext('db:vd-per-kg', default='0', namespaces=NS)
            vd_per_kg = float(vd_text)
            pb_text = pk_elem.findtext('db:protein-binding-fraction', default='0', namespaces=NS)
            pb_frac = float(pb_text)

            tr_elem = pk_elem.find('db:therapeutic-range', NS)
            if tr_elem is not None:
                t_min = float(tr_elem.findtext('db:min-effective', default='0', namespaces=NS))
                t_max = float(tr_elem.findtext('db:max-safe', default='0', namespaces=NS))

        drugs.append({
            'drugbank_id': did,
            'name': name,
            'half_life_text': half_life_text,
            'volume_of_distribution_L_per_kg': vd_per_kg,
            'protein_binding_fraction': pb_frac,
            'therapeutic_min_mg_L': t_min,
            'therapeutic_max_mg_L': t_max,
        })

    return drugs


# ═══════════════════════════════════════════
# Half-life text parser
# ═══════════════════════════════════════════

UNIT_FACTORS = {
    "sec": 1 / 3600, "secs": 1 / 3600, "second": 1 / 3600, "seconds": 1 / 3600,
    "min": 1 / 60, "mins": 1 / 60, "minute": 1 / 60, "minutes": 1 / 60,
    "h": 1, "hr": 1, "hrs": 1, "hour": 1, "hours": 1,
    "day": 24, "days": 24,
    "week": 168, "weeks": 168,
}

UNIT_RE = "|".join(sorted(UNIT_FACTORS.keys(), key=len, reverse=True))


def decode_html(text):
    replacements = {
        "&plusmn;": "\u00b1", "&alpha;": "\u03b1", "&beta;": "\u03b2",
        "&lt;": "<", "&gt;": ">", "&amp;": "&",
        "&ndash;": "\u2013", "&mdash;": "\u2014",
    }
    for entity, char in replacements.items():
        text = text.replace(entity, char)
    text = re.sub(r"<[^>]+>", "", text)
    return text


def unit_to_hours(unit_str):
    u = unit_str.lower().strip().rstrip(".")
    if u in UNIT_FACTORS:
        return UNIT_FACTORS[u]
    for k, v in sorted(UNIT_FACTORS.items(), key=lambda x: -len(x[0])):
        if u.startswith(k):
            return v
    return 1.0


def split_sentences(text):
    parts = re.split(r'(?<=\.)\s+(?=[A-Z])|(?<=\.)\s*(?=\n)|;\s*|\n+', text)
    return [p.strip() for p in parts if p.strip()]


def select_iv_segment(text):
    has_iv = bool(re.search(r'\bIV\b|intravenous|I\.V\.', text, re.IGNORECASE))
    has_other_routes = bool(re.search(
        r'\boral\b|\bintranasal\b|\bsubq\b|\bsubcutaneous\b|\bIM\b|\bintramuscular\b',
        text, re.IGNORECASE
    ))
    if not has_iv or not has_other_routes:
        return text
    sentences = split_sentences(text)
    iv_sents = [s for s in sentences if re.search(r'\bIV\b|intravenous|I\.V\.', s, re.IGNORECASE)]
    if iv_sents:
        return " ".join(iv_sents)
    m = re.search(r'(?:IV|I\.V\.|intravenous)\b.+?(?=\.\s|$)', text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(0)
    return text


def select_adult_segment(text):
    has_pop_variants = bool(re.search(
        r'\bchildren\b|\bpediatric\b|\binfant|\bimpair|\bdialysis\b|\bdisease'
        r'|\bhealthy\s+adults\b|\bhealthy\s+subjects\b|\bnormal\s+renal',
        text, re.IGNORECASE
    ))
    if not has_pop_variants:
        return text

    m = re.search(
        r'(\d[\d.\s\-to+/±]*(?:' + UNIT_RE + r'))\s+(?:in\s+)?(?:healthy\s+)?adults',
        text, re.IGNORECASE
    )
    if m:
        return m.group(0)

    m = re.search(r'Normal\s+renal\s+function[:\s]+[^.;]+', text, re.IGNORECASE)
    if m:
        return m.group(0)

    m = re.search(r'(?:in|for)\s+(?:healthy\s+)?adults[^.;]*', text, re.IGNORECASE)
    if m:
        pos = m.start()
        start = max(0, text.rfind(".", 0, pos) + 1)
        and_pos = text.rfind(" and ", 0, pos)
        if and_pos > start:
            start = and_pos + 5
        return text[start:m.end()].strip()

    return text


def select_terminal_phase(text):
    elim_hl = re.search(
        r'elimination\s+half[- ]?life\s+(?:of\s+|is\s+)?(.+?)(?:\.|$)',
        text, re.IGNORECASE
    )
    circ_hl = re.search(r'circulation\s+half[- ]?life', text, re.IGNORECASE)
    if elim_hl and circ_hl:
        return elim_hl.group(0)

    phase_markers = [
        (r'\bterminal\b', 'terminal'),
        (r'\belimination\b', 'elimination'),
        (r'\b\u03b2\b|\bbeta\b', 'beta'),
        (r'\bsecond\s+phase\b', 'second'),
    ]

    has_multiphase = bool(re.search(
        r'biphasic|\binitial\b|\b\u03b1\b|\balpha\b|\bdistribution\b|'
        r'\bfirst\s+phase\b|\bterminal\b|\bsecond\s+phase\b|\b\u03b2\b|\bbeta\b'
        r'|\bcirculation\b.*\belimination\b',
        text, re.IGNORECASE
    ))

    if not has_multiphase:
        if elim_hl:
            return elim_hl.group(0)
        return text

    for pattern, _ in phase_markers:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            pos = m.start()
            start = pos
            for sep in [","]:
                sp = text.rfind(sep, 0, pos)
                if sp >= 0:
                    start = sp + 1
                    break
            else:
                start = 0

            end = len(text)
            for ep_match in re.finditer(r'\.\s|\.(?=$)', text[m.end():]):
                end = m.end() + ep_match.start() + 1
                break

            return text[start:end].strip()

    return text


def extract_value_hours(text):
    text = text.strip()

    m = re.search(
        r'(?:approximately|about|~)\s*([\d.]+)\s*(' + UNIT_RE + r')\b',
        text, re.IGNORECASE
    )
    if m:
        return float(m.group(1)) * unit_to_hours(m.group(2))

    m = re.search(
        r'([\d.]+)\s*(?:\u00b1|\+/?-)\s*[\d.]+\s*(' + UNIT_RE + r')\b',
        text, re.IGNORECASE
    )
    if m:
        return float(m.group(1)) * unit_to_hours(m.group(2))

    m = re.search(
        r'([\d.]+)\s*[-\u2013]\s*([\d.]+)\s*(' + UNIT_RE + r')\s*\(',
        text, re.IGNORECASE
    )
    if m:
        v1, v2 = float(m.group(1)), float(m.group(2))
        factor = unit_to_hours(m.group(3))
        return math.sqrt(v1 * v2) * factor

    m = re.search(
        r'([\d.]+)\s*(' + UNIT_RE + r')\s*\(',
        text, re.IGNORECASE
    )
    if m:
        return float(m.group(1)) * unit_to_hours(m.group(2))

    m = re.search(
        r'([\d.]+)\s*(' + UNIT_RE + r')\s*[-\u2013]\s*([\d.]+)\s*(' + UNIT_RE + r')\b',
        text, re.IGNORECASE
    )
    if m:
        v1 = float(m.group(1)) * unit_to_hours(m.group(2))
        v2 = float(m.group(3)) * unit_to_hours(m.group(4))
        return math.sqrt(v1 * v2)

    m = re.search(
        r'([\d.]+)\s*[-\u2013]\s*([\d.]+)\s*(' + UNIT_RE + r')\b',
        text, re.IGNORECASE
    )
    if m:
        v1, v2 = float(m.group(1)), float(m.group(2))
        factor = unit_to_hours(m.group(3))
        return math.sqrt(v1 * v2) * factor

    m = re.search(
        r'([\d.]+)\s+to\s+([\d.]+)\s*(' + UNIT_RE + r')\b',
        text, re.IGNORECASE
    )
    if m:
        v1, v2 = float(m.group(1)), float(m.group(2))
        factor = unit_to_hours(m.group(3))
        return math.sqrt(v1 * v2) * factor

    m = re.search(
        r'(?:less\s+than|<)\s*([\d.]+)\s*(' + UNIT_RE + r')\b',
        text, re.IGNORECASE
    )
    if m:
        return float(m.group(1)) * unit_to_hours(m.group(2))

    m = re.search(
        r'([\d.]+)\s*(' + UNIT_RE + r')\b',
        text, re.IGNORECASE
    )
    if m:
        return float(m.group(1)) * unit_to_hours(m.group(2))

    return None


def parse_half_life(text):
    text = decode_html(text)
    segment = select_iv_segment(text)
    segment = select_adult_segment(segment)
    segment = select_terminal_phase(segment)
    value = extract_value_hours(segment)
    if value is not None:
        return value
    value = extract_value_hours(text)
    if value is not None:
        return value
    raise ValueError(f"Could not parse half-life from: {text}")


# ═══════════════════════════════════════════
# PK computation (one-compartment model)
# ═══════════════════════════════════════════

def compute_pk_params(t_half, dose_mg, tau_h, weight_kg, vd_per_kg, bioavailability):
    ke = math.log(2) / t_half
    vd = vd_per_kg * weight_kg
    cl = ke * vd
    eff_dose = dose_mg * bioavailability

    exp_ke_tau = math.exp(-ke * tau_h)
    R = 1.0 / (1.0 - exp_ke_tau)
    cmax_ss = (eff_dose / vd) * R
    cmin_ss = cmax_ss * exp_ke_tau
    auc_ss = eff_dose / cl
    t90 = math.log(10) / ke

    return {
        "ke": ke, "vd": vd, "cl": cl, "R": R,
        "cmax_ss": cmax_ss, "cmin_ss": cmin_ss,
        "auc_ss": auc_ss, "t90": t90,
    }


def classify_therapeutic_status(cmin, cmax, t_min, t_max):
    below = cmin < t_min
    above = cmax > t_max
    if below and above:
        return "both_violated"
    elif below:
        return "below_min"
    elif above:
        return "above_max"
    else:
        return "in_range"


def find_optimal_interval(dose_mg, weight_kg, vd_per_kg, bioavailability,
                          t_half, t_min, t_max):
    ke = math.log(2) / t_half
    vd = vd_per_kg * weight_kg
    eff_dose = dose_mg * bioavailability
    c0 = eff_dose / vd

    if c0 > t_max:
        return None

    best = None
    for tau in range(1, 721):
        exp_val = math.exp(-ke * tau)
        R = 1.0 / (1.0 - exp_val)
        cmax = c0 * R
        cmin = cmax * exp_val
        if cmin >= t_min and cmax <= t_max:
            best = tau

    return best


# ═══════════════════════════════════════════
# Main
# ═══════════════════════════════════════════

def main():
    # Parse DrugBank XML
    drugs = parse_drugbank_xml("/app/drugbank_excerpt.xml")

    # Load dosing scenarios
    with open("/app/dosing_scenarios.json") as f:
        scenarios = json.load(f)

    drug_map = {d["drugbank_id"]: d for d in drugs}

    # Parse half-lives
    extractions = []
    parsed_hl = {}

    for drug in drugs:
        did = drug["drugbank_id"]
        hl = parse_half_life(drug["half_life_text"])
        ke = math.log(2) / hl
        parsed_hl[did] = hl
        extractions.append({
            "drugbank_id": did,
            "parsed_half_life_hours": round(hl, 6),
            "elimination_rate_constant_per_h": round(ke, 6),
        })

    # Analyze scenarios
    analyses = []

    for sc in scenarios:
        sid = sc["scenario_id"]
        did = sc["drugbank_id"]
        drug = drug_map[did]
        t_half = parsed_hl[did]

        dose = sc["dose_mg"]
        tau = sc["dosing_interval_h"]
        weight = sc["patient_weight_kg"]
        F = sc["bioavailability"]
        vd_per_kg = drug["volume_of_distribution_L_per_kg"]
        t_min = drug["therapeutic_min_mg_L"]
        t_max = drug["therapeutic_max_mg_L"]

        pk = compute_pk_params(t_half, dose, tau, weight, vd_per_kg, F)
        status = classify_therapeutic_status(
            pk["cmin_ss"], pk["cmax_ss"], t_min, t_max
        )

        rec_interval = None
        if status != "in_range":
            rec_interval = find_optimal_interval(
                dose, weight, vd_per_kg, F, t_half, t_min, t_max
            )

        analyses.append({
            "scenario_id": sid,
            "drugbank_id": did,
            "parsed_half_life_hours": round(t_half, 6),
            "ke_per_h": round(pk["ke"], 6),
            "vd_L": round(pk["vd"], 6),
            "clearance_L_per_h": round(pk["cl"], 6),
            "accumulation_factor": round(pk["R"], 6),
            "cmax_steady_state_mg_L": round(pk["cmax_ss"], 6),
            "cmin_steady_state_mg_L": round(pk["cmin_ss"], 6),
            "auc_steady_state_mg_h_per_L": round(pk["auc_ss"], 6),
            "time_to_90pct_steady_state_h": round(pk["t90"], 6),
            "therapeutic_status": status,
            "recommended_interval_h": rec_interval,
        })

    os.makedirs("/app/output", exist_ok=True)
    result = {
        "drug_extractions": extractions,
        "scenario_analyses": analyses,
    }
    with open("/app/output/results.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Wrote {len(extractions)} drug extractions and {len(analyses)} scenario analyses")


if __name__ == "__main__":
    main()
