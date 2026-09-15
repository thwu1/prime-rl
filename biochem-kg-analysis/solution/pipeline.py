"""

Pipeline: Biochemical Knowledge Graph Conformance Audit
Parses NuBBE ontology, knowledge base, and prediction results.
Cross-validates schema conformance. Produces /app/report.json.
"""
import json
import os
import re
import csv
from ast import literal_eval
from collections import defaultdict

from rdflib import Graph, RDF, RDFS, OWL, Namespace, URIRef


NUBBE = Namespace("http://nubbe.db/")
NUBBEPROP = Namespace("http://nubbe.db/property/")


def local_name(uri):
    """Extract local name from a URI."""
    s = str(uri)
    if s.startswith(str(NUBBE)):
        return s[len(str(NUBBE)):]
    return s.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def parse_ontology(path):
    g = Graph()
    g.parse(path, format="turtle")

    # Collect all OWL classes in the nubbe.db namespace
    classes = set()
    for s in g.subjects(RDF.type, OWL.Class):
        if str(s).startswith(str(NUBBE)):
            classes.add(s)

    # Collect datatype properties
    dt_props = set()
    for s in g.subjects(RDF.type, OWL.DatatypeProperty):
        dt_props.add(s)

    # Build subClassOf map (child -> parent) for defined classes
    subclass_of = {}
    for child, parent in g.subject_objects(RDFS.subClassOf):
        if child in classes:
            subclass_of[child] = parent

    # Find broken references: classes referencing undeclared superclasses
    broken_refs = []
    for cls, parent in subclass_of.items():
        if parent == OWL.Thing:
            continue
        if parent not in classes:
            broken_refs.append({
                "class": local_name(cls),
                "target": local_name(parent),
            })
    broken_refs.sort(key=lambda x: x["class"])

    # Compute max hierarchy depth via DFS on well-formed chains
    children_map = defaultdict(list)
    roots = []
    for cls in classes:
        parent = subclass_of.get(cls)
        if parent is None or parent == OWL.Thing or parent not in classes:
            roots.append(cls)
        else:
            children_map[parent].append(cls)

    def max_depth(node):
        kids = children_map.get(node, [])
        if not kids:
            return 0
        return 1 + max(max_depth(c) for c in kids)

    depth = max(max_depth(r) for r in roots) if roots else 0

    ontology_result = {
        "num_classes": len(classes),
        "num_datatype_properties": len(dt_props),
        "max_hierarchy_depth": depth,
        "broken_references": broken_refs,
    }

    return ontology_result, dt_props


def analyze_conformance(dt_props, kb_path):
    """Cross-validate property names between ontology and KB."""
    # Get ontology property local names
    onto_names = set()
    for prop in dt_props:
        name = str(prop).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        onto_names.add(name)

    # Get KB property local names
    kb_names = set()
    with open(kb_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r'<[^>]+>\s+<([^>]+)>\s+"[^"]*"', line)
            if match:
                prop_uri = match.group(1)
                name = prop_uri.rsplit("/", 1)[-1]
                kb_names.add(name)

    # Find case mismatches: same when lowered, different when not
    mismatches = []
    for onto_name in sorted(onto_names):
        for kb_name in sorted(kb_names):
            if onto_name != kb_name and onto_name.lower() == kb_name.lower():
                mismatches.append({
                    "ontology_name": onto_name,
                    "kb_name": kb_name,
                })

    return {
        "property_name_mismatches": mismatches,
    }


def parse_kb(path):
    compounds = defaultdict(dict)
    num_triples = 0

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # N-Triples: <subject> <predicate> "object" .
            match = re.match(r'<([^>]+)>\s+<([^>]+)>\s+"([^"]*)"', line)
            if match:
                num_triples += 1
                subj, pred, obj = match.groups()
                comp_match = re.match(r"http://nubbe\.db/(\d+)$", subj)
                if comp_match:
                    comp_id = int(comp_match.group(1))
                    prop_name = pred.replace("http://nubbe.db/property/", "")
                    compounds[comp_id][prop_name] = obj

    # Find Lipinski violators
    violators = []
    for comp_id, props in compounds.items():
        viol_str = props.get("numberOfLipinskiViolations", "0")
        if int(viol_str) > 0:
            violators.append(comp_id)
    violators.sort()

    return {
        "num_compounds": len(compounds),
        "num_triples": num_triples,
        "lipinski_violators": violators,
    }


def hits_at_k(k, true_list, pred_list):
    """Compute hits@k metric."""
    hits = []
    for i, t in enumerate(true_list):
        hit = False
        preds = pred_list[i][1]
        for j, p in enumerate(preds):
            if j >= k:
                break
            if t[1] == p:
                hits.append(1)
                hit = True
                break
        if not hit:
            hits.append(0)
    return sum(hits) / len(hits) if hits else 0.0


def mrr(true_list, pred_list):
    """Compute MRR. Items not found in ranking are excluded from mean."""
    rrs = []
    for i, t in enumerate(true_list):
        preds = pred_list[i][1]
        for j, p in enumerate(preds):
            if t[1] == p:
                rrs.append(1.0 / (j + 1))
                break
    return sum(rrs) / len(rrs) if rrs else 0.0


def parse_predictions(pred_dir):
    results = []

    for fname in sorted(os.listdir(pred_dir)):
        if not fname.endswith(".csv"):
            continue

        # Parse filename: knn_results_{algo}_{split}_{eg1}_{eg2}_{iter}_{stage}.csv
        rest = fname.replace("knn_results_", "").replace(".csv", "")
        parts = rest.split("_")
        stage = parts[-1]
        algorithm = "_".join(parts[:-5])

        # Read and parse CSV
        filepath = os.path.join(pred_dir, fname)
        trues = []
        preds = []
        with open(filepath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trues.append(literal_eval(row["true"]))
                preds.append(literal_eval(row["restored"]))

        results.append({
            "algorithm": algorithm,
            "stage": stage,
            "hits_at_1": hits_at_k(1, trues, preds),
            "hits_at_3": hits_at_k(3, trues, preds),
            "mrr": mrr(trues, preds),
        })

    # Aggregate by (algorithm, stage) — average across iterations
    agg = defaultdict(lambda: {"hits_at_1": [], "hits_at_3": [], "mrr": []})
    for r in results:
        key = (r["algorithm"], r["stage"])
        agg[key]["hits_at_1"].append(r["hits_at_1"])
        agg[key]["hits_at_3"].append(r["hits_at_3"])
        agg[key]["mrr"].append(r["mrr"])

    metrics = []
    for (algo, stage), vals in sorted(agg.items()):
        metrics.append({
            "algorithm": algo,
            "stage": stage,
            "hits_at_1": sum(vals["hits_at_1"]) / len(vals["hits_at_1"]),
            "hits_at_3": sum(vals["hits_at_3"]) / len(vals["hits_at_3"]),
            "mrr": sum(vals["mrr"]) / len(vals["mrr"]),
        })

    # Find best algorithm by average hits@1 across all stages
    algo_hits1 = defaultdict(list)
    for m in metrics:
        algo_hits1[m["algorithm"]].append(m["hits_at_1"])
    best_algo = max(algo_hits1, key=lambda a: sum(algo_hits1[a]) / len(algo_hits1[a]))

    return {
        "metrics": metrics,
        "best_hits1_algorithm": best_algo,
    }


def main():
    ontology_result, dt_props = parse_ontology("/app/data/ontology.ttl")

    report = {
        "ontology": ontology_result,
        "conformance": analyze_conformance(dt_props, "/app/data/kb.nt"),
        "kb": parse_kb("/app/data/kb.nt"),
        "evaluation": parse_predictions("/app/data/predictions/"),
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/report.json")


if __name__ == "__main__":
    main()
