#!/usr/bin/env python3
"""
Legal Citation Evaluation Pipeline
Integrates data from SQLite (with parallel citations), GNU Rec format
(court hierarchy), nested JSON (error detection), JSONL (supplementary
responses), and YAML (configuration). Computes citation F1 with parallel
citation resolution, jurisdiction-weighted F1, MAR, normalization,
fabrication rate, and error detection with severity weighting.
"""

import json
import os
import re
import sqlite3
from collections import defaultdict

import yaml


# ============================================================
# GNU Rec Format Parser
# ============================================================

def parse_rec_file(path):
    """Parse a GNU recutils .rec file into a list of dicts."""
    records = []
    current = {}
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            # Skip type descriptor lines and comments
            if line.startswith("%") or line.startswith("#"):
                continue
            if not line.strip():
                if current:
                    records.append(current)
                    current = {}
                continue
            if ":" in line:
                key, _, value = line.partition(":")
                current[key.strip()] = value.strip()
    if current:
        records.append(current)
    return records


# ============================================================
# Citation Extraction
# ============================================================

_REPORTERS = [
    # Compound state reporters (must precede simpler patterns)
    r"Ohio\s+St\.\s*(?:2d|3d)",
    r"Cal\.\s*Rptr\.(?:\s*(?:2d|3d))?",
    r"Cal\.\s*App\.(?:\s*(?:2d|3d|4th|5th))?",
    r"Or\.\s*App\.",
    r"Wash\.\s*(?:2d|App\.)?",
    r"Ill\.\s*(?:2d|App\.(?:\s*(?:2d|3d))?)?",
    r"N\.Y\.\s*(?:2d|3d|S\.(?:2d|3d))?",
    r"Wis\.\s*2d",
    r"Mass\.\s*App\.\s*Ct\.",
    r"N\.J\.\s*Super\.",
    r"Md\.\s*App\.",
    r"Mich\.\s*App\.",
    r"Kan\.\s*App\.\s*2d",
    # Federal
    r"U\.S\.",
    r"S\.\s*Ct\.",
    r"L\.\s*Ed\.(?:\s*2d)?",
    r"F\.\s*Supp\.(?:\s*(?:2d|3d))?",
    r"F\.(?:\s*(?:2d|3d|4th))?",
    # Regional reporters
    r"A\.(?:2d|3d)",
    r"So\.(?:2d|3d)",
    r"S\.W\.(?:2d|3d)",
    r"N\.W\.(?:2d|3d)",
    r"N\.E\.(?:2d|3d)",
    r"S\.E\.(?:2d)?",
    r"P\.(?:2d|3d)",
    # State abbreviated reporters
    r"S\.C\.",
    r"N\.C\.",
    r"N\.J\.",
    r"N\.H\.",
    r"N\.D\.",
    r"S\.D\.",
    r"Mont\.",
    r"Kan\.",
    r"Ark\.",
    r"Haw\.",
    r"Ariz\.",
    r"Nev\.",
    r"Minn\.",
    r"Mass\.",
    r"Conn\.",
    r"Or\.",
    # State full-name reporters
    r"Idaho",
    r"Hawai'i",
    # Westlaw
    r"WL",
]

_REPORTER_ALT = "|".join(_REPORTERS)

_CITE_RE = re.compile(
    r"\b(\d{1,4})\s+(" + _REPORTER_ALT + r")\s+(\d+)\b",
    re.IGNORECASE,
)


def extract_citations(text):
    """Return de-duplicated list of citations found in text."""
    raw = _CITE_RE.findall(text)
    seen = set()
    out = []
    for vol, rep, page in raw:
        cite = "{} {} {}".format(vol, re.sub(r"\s+", " ", rep).strip(), page)
        key = cite.lower()
        if key not in seen:
            seen.add(key)
            out.append(cite)
    return out


# ============================================================
# Parallel Citation Lookup
# ============================================================

def build_parallel_map(conn):
    """Build a bidirectional mapping of parallel citations."""
    cursor = conn.cursor()
    cursor.execute("SELECT citation_a, citation_b FROM parallel_citations")
    pmap = defaultdict(set)
    for row in cursor.fetchall():
        a, b = row[0].lower().strip(), row[1].lower().strip()
        pmap[a].add(row[1])
        pmap[b].add(row[0])
    return dict(pmap)


# ============================================================
# Substring Matching & F1 (with parallel citation resolution)
# ============================================================

def _matches(pred, gt):
    """Case-insensitive substring containment in either direction."""
    p, g = pred.lower().strip(), gt.lower().strip()
    return p in g or g in p


def _matches_with_parallels(pred, gt, parallels):
    """Check match via direct substring or parallel citation equivalence."""
    if _matches(pred, gt):
        return True
    # Check parallels of pred against gt
    pk = pred.lower().strip()
    for parallel in parallels.get(pk, []):
        if _matches(parallel, gt):
            return True
    # Check pred against parallels of gt
    gk = gt.lower().strip()
    for parallel in parallels.get(gk, []):
        if _matches(pred, parallel):
            return True
    return False


def compute_f1(predictions, ground_truth, parallels):
    """Greedy one-to-one citation matching with parallel resolution."""
    n_pred = len(predictions)
    n_gt = len(ground_truth)

    if n_pred == 0 and n_gt == 0:
        return 1.0, 0
    if n_pred == 0 or n_gt == 0:
        return 0.0, 0

    gt_used = [False] * n_gt
    correct = 0
    for pred in predictions:
        for j, gt in enumerate(ground_truth):
            if not gt_used[j] and _matches_with_parallels(pred, gt, parallels):
                gt_used[j] = True
                correct += 1
                break

    prec = correct / n_pred
    rec = correct / n_gt
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return f1, correct


def count_fabrications(predictions, ground_truth, parallels):
    """Count predictions that don't match any ground truth (with parallels)."""
    return sum(
        1 for p in predictions
        if not any(_matches_with_parallels(p, g, parallels)
                   for g in ground_truth)
    )


# ============================================================
# MAR
# ============================================================

def compute_mar(items, threshold):
    """Misleading Answer Rate. Returns float or None."""
    low = [(s, c) for s, c in items if s <= threshold]
    if not low:
        return None
    return sum(1 for _, c in low if c) / len(low)


# ============================================================
# Citation Decomposition & Error Classification
# ============================================================

_DECOMPOSE_RE = re.compile(r"^(\d+)\s+(.+?)\s+(\d+)$")


def parse_citation(cite):
    """Split a citation string into (volume, reporter, page)."""
    m = _DECOMPOSE_RE.match(cite.strip())
    if m:
        return m.group(1), m.group(2).strip(), m.group(3)
    return "", cite.strip(), ""


def classify_error(cited, correct):
    """Return error type or None if citations match."""
    if cited.strip().lower() == correct.strip().lower():
        return None
    v1, r1, p1 = parse_citation(cited)
    v2, r2, p2 = parse_citation(correct)

    diffs = []
    if v1 != v2:
        diffs.append("volume")
    if r1.lower() != r2.lower():
        diffs.append("reporter")
    if p1 != p2:
        diffs.append("page")

    if len(diffs) == 1:
        return diffs[0]
    for kind in ("reporter", "volume", "page"):
        if kind in diffs:
            return kind
    return None


# ============================================================
# Main pipeline
# ============================================================

def main():
    # ---- Configuration ----
    with open("/app/data/eval_config.yaml") as fh:
        cfg = yaml.safe_load(fh)
    mar_threshold = cfg["evaluation"]["mar_threshold"]

    # ---- Read data from SQLite ----
    conn = sqlite3.connect("/app/data/benchmark.db")
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    # Model responses
    cursor.execute(
        "SELECT id, model, category, jurisdiction, model_output, "
        "reference_citations FROM model_responses"
    )
    records = []
    for row in cursor.fetchall():
        records.append({
            "id": row["id"],
            "model": row["model"],
            "category": row["category"],
            "jurisdiction": row["jurisdiction"],
            "model_output": row["model_output"],
            "reference_citations": json.loads(row["reference_citations"]),
        })

    # Build parallel citation map
    parallels = build_parallel_map(conn)
    conn.close()

    # ---- Parse court hierarchy from GNU Rec file ----
    rec_file = cfg.get("data_sources", {}).get("court_hierarchy", "")
    rec_path = os.path.join("/app/data", rec_file)
    hierarchy_weights = {}
    if rec_file and os.path.exists(rec_path):
        rec_records = parse_rec_file(rec_path)
        for rec in rec_records:
            code = rec.get("JurisdictionCode", "")
            weight = rec.get("ScoringWeight", "1.0")
            if code:
                hierarchy_weights[code] = float(weight)

    # ---- Parse error detection from nested JSON ----
    err_file = cfg.get("data_sources", {}).get("error_detection", "")
    err_path = os.path.join("/app/data", err_file)
    ed_records = []
    severity_weights = {}
    if err_file and os.path.exists(err_path):
        with open(err_path) as fh:
            err_data = json.load(fh)

        # Extract severity weights from nested structure
        cit_errors = (err_data.get("pipeline", {})
                      .get("error_detection", {})
                      .get("severity_model", {})
                      .get("weights", {})
                      .get("citation_errors", {}))
        for etype, info in cit_errors.items():
            severity_weights[etype] = info["weight"]

        # Extract error pairs from nested structure
        pairs = (err_data.get("pipeline", {})
                 .get("error_detection", {})
                 .get("evaluation_pairs", {})
                 .get("records", []))
        for pair in pairs:
            ed_records.append({
                "id": pair["id"],
                "evaluation_style": pair["style"],
                "presented_citation": pair["cited"]["full"],
                "canonical_citation": pair["canonical"]["full"],
                "perturbation_type": pair.get("perturbation"),
            })

    # ---- Load supplementary JSONL data ----
    supp_file = cfg.get("data_sources", {}).get("supplementary", "")
    supp_path = os.path.join("/app/data", supp_file)
    if supp_file and os.path.exists(supp_path):
        with open(supp_path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    records.append({
                        "id": obj["id"],
                        "model": obj["model"],
                        "category": obj["category"],
                        "jurisdiction": obj["jurisdiction"],
                        "model_output": obj["model_output"],
                        "reference_citations": obj["reference_citations"],
                    })

    # ---- Retrieval evaluation ----
    record_details = []
    model_cat_scores = defaultdict(lambda: defaultdict(list))
    model_items = defaultdict(list)
    model_weighted = defaultdict(lambda: {"wsum": 0.0, "wtotal": 0.0})
    model_fab = defaultdict(lambda: {"fabricated": 0, "total": 0})

    for rec in records:
        extracted = extract_citations(rec["model_output"])
        is_concrete = len(extracted) > 0
        f1, _ = compute_f1(extracted, rec["reference_citations"], parallels)
        score = f1 * 100.0

        model = rec["model"]
        cat = rec["category"]
        jur = rec["jurisdiction"]

        model_cat_scores[model][cat].append(score)
        model_items[model].append((score, is_concrete))

        w = hierarchy_weights.get(jur, 1.0)
        model_weighted[model]["wsum"] += w * score
        model_weighted[model]["wtotal"] += w

        n_fab = count_fabrications(
            extracted, rec["reference_citations"], parallels
        )
        model_fab[model]["fabricated"] += n_fab
        model_fab[model]["total"] += len(extracted)

        record_details.append({
            "id": rec["id"],
            "model": model,
            "f1_score": round(score, 4),
            "is_concrete": is_concrete,
        })

    # Per-model, per-category averages + weighted overall
    retrieval_f1 = {}
    for model in sorted(model_cat_scores):
        entry = {}
        all_scores = []
        for cat in sorted(model_cat_scores[model]):
            vals = model_cat_scores[model][cat]
            entry[cat] = round(sum(vals) / len(vals), 2)
            all_scores.extend(vals)
        entry["overall"] = round(
            sum(all_scores) / len(all_scores), 2
        ) if all_scores else 0.0
        mw = model_weighted[model]
        entry["weighted_overall"] = round(
            mw["wsum"] / mw["wtotal"], 2
        ) if mw["wtotal"] > 0 else 0.0
        retrieval_f1[model] = entry

    # MAR
    mar_out = {"threshold": mar_threshold}
    all_items = []
    for model in sorted(model_items):
        val = compute_mar(model_items[model], mar_threshold)
        mar_out[model] = round(val, 4) if val is not None else None
        all_items.extend(model_items[model])
    overall_mar = compute_mar(all_items, mar_threshold)
    mar_out["overall"] = round(overall_mar, 4) if overall_mar is not None else None

    # Normalized overall
    categories = sorted({
        c for m in model_cat_scores for c in model_cat_scores[m]
    })
    best_per_cat = {}
    for cat in categories:
        best = 0.0
        for model in model_cat_scores:
            vals = model_cat_scores[model].get(cat, [])
            avg = sum(vals) / len(vals) if vals else 0.0
            best = max(best, avg)
        best_per_cat[cat] = best

    norm_overall = {}
    for model in sorted(model_cat_scores):
        norms = []
        for cat in categories:
            vals = model_cat_scores[model].get(cat, [])
            avg = sum(vals) / len(vals) if vals else 0.0
            norms.append(
                avg / best_per_cat[cat] if best_per_cat[cat] > 0 else 0.0
            )
        norm_overall[model] = round(
            sum(norms) / len(norms), 4
        ) if norms else 0.0

    # Fabrication rate
    fab_rates = {}
    for model in sorted(model_fab):
        total = model_fab[model]["total"]
        fabricated = model_fab[model]["fabricated"]
        fab_rates[model] = round(fabricated / total, 4) if total > 0 else 0.0

    # ---- Error detection ----
    correct_det = 0
    correct_cls = 0
    total_fake = 0
    type_counts = defaultdict(int)
    sev_total = 0.0
    sev_correct = 0.0

    for rec in ed_records:
        has_error = (rec["evaluation_style"] == "3-fake")
        det_type = classify_error(
            rec["presented_citation"], rec["canonical_citation"]
        )
        det_has_error = det_type is not None

        if det_has_error == has_error:
            correct_det += 1
        if has_error:
            total_fake += 1
            expected = rec.get("perturbation_type")
            if expected:
                type_counts[expected] += 1
            sev = severity_weights.get(expected, 1.0)
            sev_total += sev
            if det_type == expected:
                correct_cls += 1
                sev_correct += sev

    det_acc = correct_det / len(ed_records) if ed_records else 0.0
    cls_acc = correct_cls / total_fake if total_fake > 0 else 0.0
    sev_w_acc = sev_correct / sev_total if sev_total > 0 else 0.0

    # ---- Write output ----
    output = {
        "retrieval_f1": retrieval_f1,
        "mar": mar_out,
        "normalized_overall": norm_overall,
        "fabrication_rate": fab_rates,
        "error_detection": {
            "detection_accuracy": round(det_acc, 4),
            "classification_accuracy": round(cls_acc, 4),
            "severity_weighted_accuracy": round(sev_w_acc, 4),
            "type_counts": dict(type_counts),
        },
        "record_details": record_details,
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/results.json", "w") as fh:
        json.dump(output, fh, indent=2)

    print("Evaluation complete. Results written to /app/output/results.json")


if __name__ == "__main__":
    main()
