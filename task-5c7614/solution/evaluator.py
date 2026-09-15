#!/usr/bin/env python3
"""SemTab annotation evaluator -- reference implementation."""

import argparse
import csv
import json
import os
import re
import sys


# ---------------------------------------------------------------------------
# URI normalization
# ---------------------------------------------------------------------------

WIKIDATA_PREFIXES = [
    "http://www.wikidata.org/entity/",
    "https://www.wikidata.org/entity/",
]


def normalize_entity(uri):
    """Normalize entity URI to canonical http://www.wikidata.org/entity/X form."""
    uri = uri.strip()
    for prefix in WIKIDATA_PREFIXES:
        if uri.startswith(prefix):
            return "http://www.wikidata.org/entity/" + uri[len(prefix):]
    if uri and not uri.startswith("http"):
        return "http://www.wikidata.org/entity/" + uri
    return uri


def resolve_redirects(entity, redirects, max_depth=20):
    """Resolve entity through redirect chain transitively."""
    visited = set()
    current = entity
    for _ in range(max_depth):
        if current in visited:
            break
        if current not in redirects:
            break
        visited.add(current)
        current = redirects[current]
    return current


def canon(entity, redirects):
    """Full canonicalization: normalize then resolve redirects."""
    return resolve_redirects(normalize_entity(entity), redirects)


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.reader(f))


def load_cea(path):
    d = {}
    for row in load_csv(path):
        if len(row) >= 4:
            key = (row[0].strip(), row[1].strip(), row[2].strip())
            d[key] = row[3].strip()
    return d


def load_cta(path):
    d = {}
    for row in load_csv(path):
        if len(row) >= 3:
            key = (row[0].strip(), row[1].strip())
            d[key] = row[2].strip()
    return d


def load_cpa(path):
    d = {}
    for row in load_csv(path):
        if len(row) >= 4:
            key = (row[0].strip(), row[1].strip(), row[2].strip())
            d[key] = row[3].strip()
    return d


def load_confidence(path):
    d = {}
    for row in load_csv(path):
        if len(row) >= 4:
            key = (row[0].strip(), row[1].strip(), row[2].strip())
            d[key] = float(row[3].strip())
    return d


# ---------------------------------------------------------------------------
# RDF parsing
# ---------------------------------------------------------------------------

def parse_turtle_hierarchy(filepath):
    """Parse type hierarchy from Turtle RDF file.

    Extracts rdfs:subClassOf relationships to build a parent map.
    Returns dict mapping entity URI -> parent URI (or None for roots).
    """
    prefixes = {}
    parent_map = {}
    all_entities = set()
    current_subject = None

    with open(filepath) as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            if not stripped or stripped.startswith("#"):
                continue

            m = re.match(r"@prefix\s+(\w*)\s*:\s*<([^>]+)>\s*\.", stripped)
            if m:
                prefixes[m.group(1)] = m.group(2)
                continue

            def expand(term):
                term = term.strip().rstrip(" .;")
                if term.startswith("<") and term.endswith(">"):
                    return term[1:-1]
                if term.startswith('"'):
                    return term.strip('"')
                for pfx, uri in prefixes.items():
                    if term.startswith(pfx + ":"):
                        return uri + term[len(pfx) + 1 :]
                return term

            if not line[0].isspace():
                tokens = stripped.split(None, 2)
                if len(tokens) >= 3:
                    current_subject = expand(tokens[0])
                    pred_uri = expand(tokens[1])
                    obj = expand(tokens[2])
                    all_entities.add(current_subject)
                    if pred_uri.endswith("subClassOf"):
                        parent_map[current_subject] = obj
            elif current_subject:
                tokens = stripped.split(None, 1)
                if len(tokens) >= 2:
                    pred_uri = expand(tokens[0])
                    obj = expand(tokens[1])
                    if pred_uri.endswith("subClassOf"):
                        parent_map[current_subject] = obj

    for e in all_entities:
        if e not in parent_map:
            parent_map[e] = None

    return parent_map


def parse_ntriples_redirects(filepath):
    """Parse entity redirects from N-Triples RDF file (owl:sameAs triples)."""
    redirects = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"<([^>]+)>\s+<([^>]+)>\s+<([^>]+)>\s*\.", line)
            if m and "sameAs" in m.group(2):
                redirects[normalize_entity(m.group(1))] = normalize_entity(
                    m.group(3)
                )
    return redirects


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_prf(gold, pred, redirects):
    correct = 0
    for key, pred_entity in pred.items():
        if key in gold:
            if canon(pred_entity, redirects) == canon(gold[key], redirects):
                correct += 1
    n_pred = len(pred)
    n_gold = len(gold)
    precision = correct / n_pred if n_pred > 0 else 0.0
    recall = correct / n_gold if n_gold > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {"precision": precision, "recall": recall, "f1": f1}


def compute_prf_per_table(gold, pred, redirects):
    tables = set()
    for key in list(gold.keys()) + list(pred.keys()):
        tables.add(key[0])
    result = {}
    for tbl in sorted(tables):
        tbl_gold = {k: v for k, v in gold.items() if k[0] == tbl}
        tbl_pred = {k: v for k, v in pred.items() if k[0] == tbl}
        result[tbl] = compute_prf(tbl_gold, tbl_pred, redirects)
    return result


# ---------------------------------------------------------------------------
# Hierarchy-aware CTA scoring
# ---------------------------------------------------------------------------

def get_ancestors(entity, parent_map):
    ancestors = []
    current = entity
    visited = set()
    while current is not None and current not in visited:
        ancestors.append(current)
        visited.add(current)
        current = parent_map.get(current)
    return ancestors


def tree_distance(e1, e2, parent_map):
    if e1 == e2:
        return 0
    ancestors1 = get_ancestors(e1, parent_map)
    ancestors2 = get_ancestors(e2, parent_map)
    set2 = set(ancestors2)
    lca = None
    for a in ancestors1:
        if a in set2:
            lca = a
            break
    if lca is None:
        return -1
    d1 = ancestors1.index(lca)
    d2 = ancestors2.index(lca)
    return d1 + d2


def compute_hierarchy_cta(gold, pred, redirects, parent_map):
    score_sum = 0.0
    for key, pred_type in pred.items():
        if key in gold:
            pt = canon(pred_type, redirects)
            gt = canon(gold[key], redirects)
            if pt == gt:
                score_sum += 1.0
            else:
                d = tree_distance(pt, gt, parent_map)
                if d > 0:
                    score_sum += 1.0 / (1.0 + d)
    n_pred = len(pred)
    n_gold = len(gold)
    precision = score_sum / n_pred if n_pred > 0 else 0.0
    recall = score_sum / n_gold if n_gold > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {"precision": precision, "recall": recall, "f1": f1}


# ---------------------------------------------------------------------------
# AURC (Area Under Risk-Coverage Curve)
# ---------------------------------------------------------------------------

def compute_aurc(gold, pred, confidence, redirects):
    items = []
    for key, pred_entity in pred.items():
        conf = confidence.get(key, 0.0)
        is_correct = key in gold and canon(pred_entity, redirects) == canon(
            gold[key], redirects
        )
        items.append((conf, is_correct))
    if not items:
        return 0.0
    items.sort(key=lambda x: -x[0])
    n = len(items)
    errors = 0
    risk_sum = 0.0
    for k, (conf, correct) in enumerate(items, 1):
        if not correct:
            errors += 1
        risk_sum += errors / k
    return risk_sum / n


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def evaluate(data_dir, output_path):
    config_path = os.path.join(data_dir, "config.json")
    with open(config_path) as f:
        config = json.load(f)

    gold_dir = os.path.join(data_dir, "gold")
    pred_dir = os.path.join(data_dir, "predictions")
    ontology_dir = os.path.join(data_dir, "ontology")
    systems = config["systems"]
    systems_with_conf = config.get("systems_with_confidence", [])

    # Load gold
    gold_cea = load_cea(os.path.join(gold_dir, "cea.csv"))
    gold_cta = load_cta(os.path.join(gold_dir, "cta.csv"))
    gold_cpa = load_cpa(os.path.join(gold_dir, "cpa.csv"))

    # Load ontology (RDF formats)
    ttl_path = os.path.join(ontology_dir, "type_hierarchy.ttl")
    nt_path = os.path.join(ontology_dir, "entity_redirects.nt")

    parent_map = parse_turtle_hierarchy(ttl_path)
    redirects = parse_ntriples_redirects(nt_path)

    results = {"systems": {}, "ranking": []}

    for sys_name in systems:
        sys_dir = os.path.join(pred_dir, sys_name)

        pred_cea = load_cea(os.path.join(sys_dir, "cea.csv"))
        pred_cta = load_cta(os.path.join(sys_dir, "cta.csv"))
        pred_cpa = load_cpa(os.path.join(sys_dir, "cpa.csv"))

        cea_metrics = compute_prf(gold_cea, pred_cea, redirects)
        cta_metrics = compute_prf(gold_cta, pred_cta, redirects)
        cpa_metrics = compute_prf(gold_cpa, pred_cpa, redirects)
        cta_hierarchy = compute_hierarchy_cta(
            gold_cta, pred_cta, redirects, parent_map
        )
        cea_per_table = compute_prf_per_table(gold_cea, pred_cea, redirects)

        aurc = None
        if sys_name in systems_with_conf:
            conf_path = os.path.join(sys_dir, "cea_confidence.csv")
            if os.path.exists(conf_path):
                confidence = load_confidence(conf_path)
                aurc = compute_aurc(gold_cea, pred_cea, confidence, redirects)

        results["systems"][sys_name] = {
            "cea": cea_metrics,
            "cta": cta_metrics,
            "cpa": cpa_metrics,
            "cta_hierarchy": cta_hierarchy,
            "cea_per_table": cea_per_table,
            "aurc": aurc,
        }

    ranked = sorted(
        systems,
        key=lambda s: (
            -results["systems"][s]["cea"]["f1"],
            -results["systems"][s]["cea"]["precision"],
        ),
    )
    results["ranking"] = ranked

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SemTab Evaluation")
    parser.add_argument("--data-dir", default="/opt/semtab_data")
    parser.add_argument("--output", default="/app/results.json")
    args = parser.parse_args()
    evaluate(args.data_dir, args.output)
