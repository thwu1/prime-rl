#!/usr/bin/env python3
"""LegalCiteBench evaluation pipeline.

Reconciles data from SQLite (model responses), JSONL (ground truth),
XML (parallel citation authority), and YAML+JSON (scoring config)
to produce aggregate evaluation metrics.
"""


import json
import re
import sqlite3
import xml.etree.ElementTree as ET
import yaml

DB_PATH = "/app/citation_eval.db"
GT_PATH = "/app/ground_truth_manifest.jsonl"
AUTHORITY_PATH = "/app/citation_authority.xml"
YAML_CONFIG_PATH = "/app/scoring_config.yaml"
JSON_OVERRIDES_PATH = "/app/scoring_overrides.json"
OUTPUT_PATH = "/app/results.json"


def deep_merge(base, override):
    """Recursively merge override dict into base dict."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config():
    """Load and merge YAML base config with JSON overrides."""
    with open(YAML_CONFIG_PATH) as f:
        base = yaml.safe_load(f)
    with open(JSON_OVERRIDES_PATH) as f:
        overrides = json.load(f)
    return deep_merge(base, overrides)


def load_ground_truth():
    """Load ground truth from JSONL manifest.

    Returns dict: instance_id -> ground truth value
    (list of citations for cat1/cat2, description string for cat3)
    """
    gt = {}
    with open(GT_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            iid = entry["instance_id"]
            cat = entry["category"]
            annotations = entry["annotations"]
            if cat in ("cat1", "cat2"):
                gt[iid] = annotations["citations"]
            elif cat == "cat3":
                gt[iid] = annotations["description"]
    return gt


def load_authority_index():
    """Load parallel citation groups from XML authority index.

    Returns list of (group_id, citation_text) tuples.
    """
    tree = ET.parse(AUTHORITY_PATH)
    root = tree.getroot()
    entries = []
    for group in root.findall(".//case_group"):
        gid = group.get("id")
        for cite in group.findall("citation"):
            if cite.text:
                entries.append((gid, cite.text.strip()))
    return entries


def extract_citations(text):
    """Extract legal citation strings from model output text.

    Handles major US legal citation formats including federal, regional,
    state-specific, neutral, and Westlaw citations.
    """
    patterns = [
        # US Reports: 466 U.S. 668
        r'\d+\s+U\.S\.\s+\d+',

        # Federal Reporter: 807 F.3d 619, 576 F.2d 236, F.Supp.2d etc.
        r'\d+\s+F\.(?:Supp\.)?(?:\d[a-z])?\s+\d+',

        # South Western Reporter: 973 S.W.2d 485, 56 S.W.3d 842
        r'\d+\s+S\.W\.(?:\d[a-z])?\s+\d+',

        # North Western Reporter: 522 N.W.2d 439
        r'\d+\s+N\.W\.(?:\d[a-z])?\s+\d+',

        # North Eastern Reporter: 946 N.E.2d 665
        r'\d+\s+N\.E\.(?:\d[a-z])?\s+\d+',

        # South Eastern Reporter: 589 S.E.2d 760
        r'\d+\s+S\.E\.(?:\d[a-z])?\s+\d+',

        # Southern Reporter: 36 So.3d 84, 707 So.2d 827
        r'\d+\s+So\.?\s*\d[a-z]\s+\d+',

        # Atlantic Reporter: 205 A.3d 445
        r'\d+\s+A\.(?:\d[a-z])?\s+\d+',

        # Pacific Reporter: 635 P.2d 730, 425 P.3d 115
        r'\d+\s+P\.(?:\d[a-z])?\s+\d+',

        # Ohio State Reports: 149 Ohio St. 3d 628, 100 Ohio St. 200
        r'\d+\s+Ohio\s+St\.?\s*(?:\d[a-z]\s+)?\d+',

        # Oregon Appellate Reports: 284 Or. App. 887
        r'\d+\s+Or\.\s+App\.\s+\d+',

        # Washington Reports with series: 96 Wash.2d 443
        r'\d+\s+Wash\.(?:\d[a-z])?\s+\d+',

        # Hawaiian reporters: 127 Hawai'i 126
        r"\d+\s+Hawai['\u2018\u2019\u02BB]i\s+\d+",

        # Hawaii abbreviated: 72 Haw. 246
        r'\d+\s+Haw\.\s+\d+',

        # South Carolina: 349 S.C. 558
        r'\d+\s+S\.C\.\s+\d+',

        # New Jersey: 224 N.J. 530
        r'\d+\s+N\.J\.\s+\d+',

        # New Hampshire: 169 N.H. 783
        r'\d+\s+N\.H\.\s+\d+',

        # Montana: 82 Mont. 250
        r'\d+\s+Mont\.\s+\d+',

        # Kansas: 303 Kan. 785
        r'\d+\s+Kan\.\s+\d+',

        # Idaho: 162 Idaho 763
        r'\d+\s+Idaho\s+\d+',

        # Florida: 131 Fla. 127
        r'\d+\s+Fla\.\s+\d+',

        # Arkansas volume-style: 350 Ark. 138
        r'\d+\s+Ark\.\s+\d+',

        # Neutral citations: 2011 ND 159, 2005 MT 310, 2002 ND 115
        r'\d{4}\s+(?:ND|MT|SD|VT|WY|ME)\s+\d+',

        # Arkansas neutral: 2012 Ark. 179, 2017 Ark. App. 384
        r'\d{4}\s+Ark\.(?:\s+App\.)?\s+\d+',

        # Westlaw: 2016 WL 1171919
        r'\d{4}\s+WL\s+\d+',
    ]

    found = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            citation = re.sub(r'\s+', ' ', match.group().strip())
            found.add(citation)

    # Deduplicate: remove citations that are substrings of other found citations
    result = []
    sorted_cites = sorted(found, key=len, reverse=True)
    for cite in sorted_cites:
        if not any(cite.lower() in existing.lower() for existing in result):
            result.append(cite)

    return result


def find_authority_groups(citation, authority_entries):
    """Find which authority groups a citation belongs to via substring matching."""
    groups = set()
    cl = citation.lower().strip()
    for gid, auth_cite in authority_entries:
        al = auth_cite.lower().strip()
        if cl in al or al in cl:
            groups.add(gid)
    return groups


def citations_match(pred, gt, authority_entries):
    """Check if predicted and ground truth citations match.

    Match via:
    1. Direct bidirectional case-insensitive substring match, OR
    2. Both belong to the same authority group (parallel citations)
    """
    pred_lower = pred.lower().strip()
    gt_lower = gt.lower().strip()
    if pred_lower in gt_lower or gt_lower in pred_lower:
        return True

    pred_groups = find_authority_groups(pred, authority_entries)
    gt_groups = find_authority_groups(gt, authority_entries)
    if pred_groups & gt_groups:
        return True

    return False


def compute_f1(predicted, ground_truth, authority_entries, scale=100):
    """Compute citation-level F1 score with parallel citation support."""
    if not predicted and not ground_truth:
        return 0.0

    matched = sum(
        1 for p in predicted
        if any(citations_match(p, g, authority_entries) for g in ground_truth)
    )

    prec = matched / len(predicted) if predicted else 0.0
    rec = matched / len(ground_truth) if ground_truth else 0.0

    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec) * scale


def score_cat3(output, variant, ground_truth):
    """Score a Cat3 instance (raw 0-5 scale)."""
    output_lower = output.lower()

    if variant == "true":
        # Check for negated error claims: "no error", "no citation error"
        has_negated = bool(re.search(
            r'\bno\s+(?:citation\s+)?error', output_lower))
        has_error = bool(re.search(
            r'\b(error|incorrect|wrong)\b', output_lower))
        if has_error and not has_negated:
            return 2
        elif re.search(r'\b(correct|accurate)\b', output_lower):
            return 5
        return 0

    elif variant == "fake":
        if not re.search(r'\b(error|incorrect|wrong)\b', output_lower):
            return 1
        match = re.search(
            r'The correct citation is:\s*(.+)$', ground_truth,
            re.IGNORECASE)
        if not match:
            return 2
        correct = match.group(1).strip()
        if correct.lower() in output_lower:
            return 5
        return 2

    return 0


def compute_mar(f1_scores, is_concrete_list, threshold):
    """Compute Misleading Answer Rate."""
    low_scoring = [
        (f1, conc) for f1, conc in zip(f1_scores, is_concrete_list)
        if f1 <= threshold
    ]
    if not low_scoring:
        return 0.0
    return sum(1 for _, conc in low_scoring if conc) / len(low_scoring)


def main():
    # Load and merge configuration
    config = load_config()
    f1_scale = config['cat1_cat2']['f1_scale']
    cat3_max = config['cat3']['raw_score_max']
    cat3_scale = config['cat3']['report_scale']
    mar_threshold = config['mar']['low_score_threshold']

    # Load ground truth from JSONL manifest
    gt_data = load_ground_truth()

    # Load parallel citation authority index
    authority = load_authority_index()

    # Connect to SQLite database for instances and model responses
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cat1_f1, cat1_conc = [], []
    cat2_f1, cat2_conc = [], []
    cat3_scores = []

    # Process Cat1
    for row in conn.execute(
            "SELECT i.instance_id, i.variant, r.response_text "
            "FROM instances i "
            "JOIN model_responses r ON i.instance_id = r.instance_id "
            "WHERE i.category = 'cat1'"):
        iid = row['instance_id']
        gt = gt_data.get(iid, [])
        preds = extract_citations(row['response_text'])
        f1 = compute_f1(preds, gt, authority, f1_scale)
        cat1_f1.append(f1)
        cat1_conc.append(len(preds) > 0)

    # Process Cat2
    for row in conn.execute(
            "SELECT i.instance_id, i.variant, r.response_text "
            "FROM instances i "
            "JOIN model_responses r ON i.instance_id = r.instance_id "
            "WHERE i.category = 'cat2'"):
        iid = row['instance_id']
        gt = gt_data.get(iid, [])
        preds = extract_citations(row['response_text'])
        f1 = compute_f1(preds, gt, authority, f1_scale)
        cat2_f1.append(f1)
        cat2_conc.append(len(preds) > 0)

    # Process Cat3
    for row in conn.execute(
            "SELECT i.instance_id, i.variant, r.response_text "
            "FROM instances i "
            "JOIN model_responses r ON i.instance_id = r.instance_id "
            "WHERE i.category = 'cat3'"):
        iid = row['instance_id']
        gt = gt_data.get(iid, "")
        s = score_cat3(row['response_text'], row['variant'], gt)
        cat3_scores.append(s)

    conn.close()

    # Aggregate metrics
    c1f1 = sum(cat1_f1) / len(cat1_f1) if cat1_f1 else 0.0
    c2f1 = sum(cat2_f1) / len(cat2_f1) if cat2_f1 else 0.0
    c3_raw = sum(cat3_scores) / len(cat3_scores) if cat3_scores else 0.0
    c3_scaled = (c3_raw / cat3_max) * cat3_scale

    c1_mar = compute_mar(cat1_f1, cat1_conc, mar_threshold)
    c2_mar = compute_mar(cat2_f1, cat2_conc, mar_threshold)
    all_f1 = cat1_f1 + cat2_f1
    all_conc = cat1_conc + cat2_conc
    o_mar = compute_mar(all_f1, all_conc, mar_threshold)

    results = {
        "cat1_mean_f1": round(c1f1, 4),
        "cat2_mean_f1": round(c2f1, 4),
        "cat3_mean_score": round(c3_scaled, 4),
        "cat1_mar": round(c1_mar, 4),
        "cat2_mar": round(c2_mar, 4),
        "overall_mar": round(o_mar, 4),
        "num_instances": len(cat1_f1) + len(cat2_f1) + len(cat3_scores),
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
