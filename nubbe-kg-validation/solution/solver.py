#!/usr/bin/env python3
"""
Solver for biochemical knowledge graph validation and evaluation task.
Parses OWL ontology, validates compound properties, computes link prediction metrics.
"""

import json
import re
import csv
import os
from collections import defaultdict
from rdflib import Graph, RDF, RDFS, OWL


def parse_european_decimal(s):
    """Convert European decimal notation (comma as separator) to float."""
    return float(s.replace(",", "."))


def analyze_ontology(filepath):
    """Parse Turtle ontology, find orphan subclass declarations and max depth."""
    g = Graph()
    g.parse(filepath, format="turtle")

    # Collect all declared owl:Class URIs
    declared_classes = set()
    for s in g.subjects(RDF.type, OWL.Class):
        declared_classes.add(str(s))

    # Collect subclass relationships and find orphans
    orphans = []
    subclass_rels = []
    owl_thing = str(OWL.Thing)

    for s, o in g.subject_objects(RDFS.subClassOf):
        s_str = str(s)
        o_str = str(o)
        if s_str not in declared_classes:
            continue
        subclass_rels.append((s_str, o_str))
        if o_str != owl_thing and o_str not in declared_classes:
            orphans.append({"class": s_str, "missing_parent": o_str})

    orphans.sort(key=lambda x: x["class"])

    # Compute max hierarchy depth via BFS from owl:Thing
    children = defaultdict(list)
    for cls, parent in subclass_rels:
        if parent == owl_thing or parent in declared_classes:
            children[parent].append(cls)

    depth = {owl_thing: 0}
    queue = [owl_thing]
    max_depth = 0
    while queue:
        node = queue.pop(0)
        for child in children.get(node, []):
            if child not in depth and child in declared_classes:
                depth[child] = depth[node] + 1
                max_depth = max(max_depth, depth[child])
                queue.append(child)

    return orphans, max_depth


def validate_lipinski(filepath):
    """Parse N-Triples KB and find Lipinski violation mismatches."""
    prop_base = "http://nubbe.db/property/"
    compounds = defaultdict(dict)

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(
                r'<([^>]+)>\s+<([^>]+)>\s+(?:<([^>]+)>|"([^"]*)")\s*\.', line
            )
            if not match:
                continue
            subj, pred = match.group(1), match.group(2)
            obj_uri, obj_lit = match.group(3), match.group(4)

            cid_match = re.match(r"http://nubbe\.db/(\d+)$", subj)
            if not cid_match:
                continue
            cid = int(cid_match.group(1))

            if obj_lit is not None:
                if pred == prop_base + "molecularMass":
                    compounds[cid]["mw"] = parse_european_decimal(obj_lit)
                elif pred == prop_base + "cLogP":
                    compounds[cid]["clogp"] = parse_european_decimal(obj_lit)
                elif pred == prop_base + "numberOfH-bondDonors":
                    compounds[cid]["hbd"] = int(obj_lit)
                elif pred == prop_base + "numberOfH-bondAcceptors":
                    compounds[cid]["hba"] = int(obj_lit)
                elif pred == prop_base + "numberOfLipinskiViolations":
                    compounds[cid]["stated"] = int(obj_lit)

    mismatches = []
    for cid in sorted(compounds.keys()):
        p = compounds[cid]
        if not all(k in p for k in ["mw", "clogp", "hbd", "hba", "stated"]):
            continue

        computed = 0
        if p["mw"] > 500:
            computed += 1
        if p["clogp"] > 5:
            computed += 1
        if p["hbd"] > 5:
            computed += 1
        if p["hba"] > 10:
            computed += 1

        if p["stated"] != computed:
            mismatches.append(
                {"compound_id": cid, "stated": p["stated"], "computed": computed}
            )

    return mismatches


def compute_metrics(csv_path):
    """Compute hits@k and MRR from prediction CSV."""
    with open(csv_path, "r") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        rows = list(reader)

    n = len(rows)
    h1 = h5 = h10 = 0
    rr_sum = 0.0

    for row in rows:
        true_target = row[1].strip()
        predictions = [r.strip() for r in row[2:12]]

        rank = None
        for i, pred in enumerate(predictions):
            if pred == true_target:
                rank = i + 1
                break

        if rank is not None:
            if rank <= 1:
                h1 += 1
            if rank <= 5:
                h5 += 1
            if rank <= 10:
                h10 += 1
            rr_sum += 1.0 / rank

    return {
        "hits_at_1": h1 / n,
        "hits_at_5": h5 / n,
        "hits_at_10": h10 / n,
        "mrr": rr_sum / n,
    }


def main():
    # Ontology analysis
    orphans, max_depth = analyze_ontology("/app/data/ontology.ttl")

    # Lipinski validation
    mismatches = validate_lipinski("/app/data/compounds.nt")

    # Link prediction metrics
    deepwalk_metrics = compute_metrics("/app/data/predictions/deepwalk.csv")
    node2vec_metrics = compute_metrics("/app/data/predictions/node2vec.csv")

    # Assemble and write output
    result = {
        "orphan_subclass_declarations": orphans,
        "max_hierarchy_depth": max_depth,
        "lipinski_mismatches": mismatches,
        "deepwalk_metrics": deepwalk_metrics,
        "node2vec_metrics": node2vec_metrics,
    }

    os.makedirs("/app/results", exist_ok=True)
    with open("/app/results/analysis.json", "w") as f:
        json.dump(result, f, indent=2)

    print("Analysis complete. Results written to /app/results/analysis.json")


if __name__ == "__main__":
    main()
