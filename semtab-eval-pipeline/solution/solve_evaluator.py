#!/usr/bin/env python3
"""
SemTab Evaluation Pipeline with OWL 2 / RDFS Entailment — Reference Solution

Implements:
1. owl:sameAs equivalence class computation (symmetric + transitive closure)
2. owl:equivalentClass expansion to mutual rdfs:subClassOf
3. rdfs:subClassOf transitive closure for CTA subsumption matching
4. rdfs:subPropertyOf transitive closure for CPA subsumption matching
5. CEA/CTA/CPA evaluation with ABSTAIN/NIL handling
6. N-Triples RDF output conforming to the evaluation ontology
"""

import csv
import json
import os

from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS, OWL, XSD

EVAL = Namespace("http://example.org/eval#")
WD_PREFIX = "http://www.wikidata.org/entity/"
WDT_PREFIX = "http://www.wikidata.org/prop/direct/"


def load_kg(path):
    g = Graph()
    g.parse(path, format="turtle")
    return g


def uri_to_short(uri):
    """Convert URI to short ID, handling both entity and property namespaces."""
    if uri.startswith(WDT_PREFIX):
        return uri[len(WDT_PREFIX):]
    if uri.startswith(WD_PREFIX):
        return uri[len(WD_PREFIX):]
    return uri


def short_to_uri(short_id):
    return WD_PREFIX + short_id


def compute_sameas_classes(g):
    """Compute owl:sameAs equivalence classes using union-find.

    owl:sameAs is reflexive, symmetric, and transitive per W3C OWL semantics.
    We process each (s, owl:sameAs, o) triple and union both directions
    to correctly handle symmetry even when only one direction is stated.
    """
    parent = {}

    def find(x):
        if x not in parent:
            parent[x] = x
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for s, _, o in g.triples((None, OWL.sameAs, None)):
        union(str(s), str(o))

    return find


def are_equivalent(e1, e2, find_func):
    """Check if two short entity IDs are in the same owl:sameAs equivalence class."""
    return find_func(short_to_uri(e1)) == find_func(short_to_uri(e2))


def compute_hierarchy_closure(g, predicate, equivalence_pred=None):
    """Compute transitive closure of a hierarchy predicate (rdfs:subClassOf or
    rdfs:subPropertyOf).

    If equivalence_pred is provided (e.g., owl:equivalentClass), expand
    equivalences into mutual sub-relations before computing the closure.
    owl:equivalentClass A B implies A rdfs:subClassOf B and B rdfs:subClassOf A.
    """
    direct_parents = {}

    # Process direct hierarchy triples
    for s, _, o in g.triples((None, predicate, None)):
        s_id = uri_to_short(str(s))
        o_id = uri_to_short(str(o))
        direct_parents.setdefault(s_id, []).append(o_id)

    # Expand equivalences into mutual sub-relations
    if equivalence_pred:
        for s, _, o in g.triples((None, equivalence_pred, None)):
            s_id = uri_to_short(str(s))
            o_id = uri_to_short(str(o))
            direct_parents.setdefault(s_id, []).append(o_id)
            direct_parents.setdefault(o_id, []).append(s_id)

    all_items = set(direct_parents.keys())
    for parents in direct_parents.values():
        all_items.update(parents)

    # BFS to compute transitive ancestors for each item
    ancestors = {}
    for item in all_items:
        anc = set()
        queue = list(direct_parents.get(item, []))
        visited = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            anc.add(current)
            queue.extend(direct_parents.get(current, []))
        ancestors[item] = anc

    # Compute descendants from ancestors
    descendants = {item: set() for item in all_items}
    for item in all_items:
        for anc in ancestors.get(item, set()):
            descendants[anc].add(item)

    return ancestors, descendants


def subsumption_matches(predicted, ground_truth, ancestors, descendants):
    """Check subsumption match: exact, ancestor, or descendant."""
    if predicted == ground_truth:
        return True
    if predicted in ancestors.get(ground_truth, set()):
        return True
    if predicted in descendants.get(ground_truth, set()):
        return True
    return False


def load_csv(path):
    rows = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            rows.append([x.strip() for x in row])
    return rows


def evaluate_cea(gt_rows, sub_rows, find_func):
    """Evaluate CEA with owl:sameAs equivalence resolution."""
    gt = {(r[0], r[1], r[2]): r[3] for r in gt_rows}

    correct = 0
    submitted = 0
    abstain_count = 0
    cell_results = {}

    for row in sub_rows:
        key = (row[0], row[1], row[2])
        pred = row[3]

        if pred.upper() == "ABSTAIN":
            abstain_count += 1
            cell_results[key] = False
            continue

        submitted += 1
        if key in gt:
            gt_entity = gt[key]
            if gt_entity.upper() == "NIL" and pred.upper() == "NIL":
                correct += 1
                cell_results[key] = True
            elif gt_entity.upper() == "NIL" or pred.upper() == "NIL":
                cell_results[key] = False
            elif are_equivalent(pred, gt_entity, find_func):
                correct += 1
                cell_results[key] = True
            else:
                cell_results[key] = False
        else:
            cell_results[key] = False

    gt_total = len(gt)
    total_subs = len(sub_rows)

    p = correct / submitted if submitted > 0 else 0.0
    r = correct / gt_total if gt_total > 0 else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    coverage = submitted / gt_total if gt_total > 0 else 0.0
    abstention_rate = abstain_count / total_subs if total_subs > 0 else 0.0

    return {
        "precision": p, "recall": r, "f1": f1,
        "coverage": coverage, "abstention_rate": abstention_rate,
    }, cell_results


def evaluate_subsumption(gt_rows, sub_rows, ancestors, descendants, key_len):
    """Evaluate CTA (key_len=2) or CPA (key_len=3) with subsumption matching."""
    if key_len == 2:
        gt = {(r[0], r[1]): r[2] for r in gt_rows}
    else:
        gt = {(r[0], r[1], r[2]): r[3] for r in gt_rows}

    correct = 0
    submitted = 0
    abstain_count = 0
    total_subs = len(sub_rows)

    for row in sub_rows:
        if key_len == 2:
            key, pred = (row[0], row[1]), row[2]
        else:
            key, pred = (row[0], row[1], row[2]), row[3]

        if pred.upper() == "ABSTAIN":
            abstain_count += 1
            continue

        submitted += 1
        if key in gt and subsumption_matches(pred, gt[key], ancestors, descendants):
            correct += 1

    gt_total = len(gt)
    p = correct / submitted if submitted > 0 else 0.0
    r = correct / gt_total if gt_total > 0 else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    coverage = submitted / gt_total if gt_total > 0 else 0.0
    abstention_rate = abstain_count / total_subs if total_subs > 0 else 0.0

    return {
        "precision": p, "recall": r, "f1": f1,
        "coverage": coverage, "abstention_rate": abstention_rate,
    }


def compute_category_metrics(cell_results, challenge_categories):
    """Compute per-category accuracy for CEA results."""
    category_metrics = {}
    for category, cell_keys in challenge_categories.items():
        total = len(cell_keys)
        correct = 0
        for cell_key in cell_keys:
            parts = cell_key.split(":")
            lookup_key = (parts[0], parts[1], parts[2])
            if lookup_key in cell_results and cell_results[lookup_key]:
                correct += 1
        accuracy = correct / total if total > 0 else 0.0
        category_metrics[category] = {
            "correct": correct,
            "total": total,
            "accuracy": accuracy,
        }
    return category_metrics


def build_ntriples_graph(results_data, systems, rankings):
    """Build an rdflib Graph with evaluation results per the eval ontology."""
    g = Graph()

    for sys_name in systems:
        for task in ["cea", "cta", "cpa"]:
            subj = URIRef(f"http://example.org/eval#{sys_name}_{task}")
            metrics = results_data["systems"][sys_name][task]

            g.add((subj, RDF.type, EVAL.Evaluation))
            g.add((subj, EVAL.system, Literal(sys_name, datatype=XSD.string)))
            g.add((subj, EVAL.task, Literal(task, datatype=XSD.string)))

            for prop, key in [("precision", "precision"), ("recall", "recall"),
                              ("f1", "f1"), ("coverage", "coverage"),
                              ("abstentionRate", "abstention_rate")]:
                g.add((subj, EVAL[prop],
                       Literal(f"{metrics[key]:.6f}", datatype=XSD.decimal)))

            rank_list = rankings[f"{task}_f1"]
            rank = rank_list.index(sys_name) + 1
            g.add((subj, EVAL.rank, Literal(rank, datatype=XSD.integer)))

    return g


def main():
    data_dir = "/data"
    submissions_dir = os.path.join(data_dir, "submissions")

    # Load RDF knowledge graph
    kg = load_kg(os.path.join(data_dir, "kg.ttl"))

    # Compute owl:sameAs equivalence classes for CEA
    find_func = compute_sameas_classes(kg)

    # Compute rdfs:subClassOf + owl:equivalentClass transitive closure for CTA
    class_ancestors, class_descendants = compute_hierarchy_closure(
        kg, RDFS.subClassOf, OWL.equivalentClass
    )

    # Compute rdfs:subPropertyOf transitive closure for CPA
    prop_ancestors, prop_descendants = compute_hierarchy_closure(
        kg, RDFS.subPropertyOf
    )

    # Load ground truth
    gt_cea = load_csv(os.path.join(data_dir, "gt_cea.csv"))
    gt_cta = load_csv(os.path.join(data_dir, "gt_cta.csv"))
    gt_cpa = load_csv(os.path.join(data_dir, "gt_cpa.csv"))

    # Load challenge categories
    with open(os.path.join(data_dir, "challenge_categories.json")) as f:
        challenge_categories = json.load(f)

    # Discover systems
    systems = sorted({
        fname.replace("_cea.csv", "")
        for fname in os.listdir(submissions_dir)
        if fname.endswith("_cea.csv")
    })

    results = {"systems": {}, "rankings": {}, "category_metrics": {}}

    for sys_name in systems:
        sub_cea = load_csv(os.path.join(submissions_dir, f"{sys_name}_cea.csv"))
        sub_cta = load_csv(os.path.join(submissions_dir, f"{sys_name}_cta.csv"))
        sub_cpa = load_csv(os.path.join(submissions_dir, f"{sys_name}_cpa.csv"))

        cea_metrics, cell_results = evaluate_cea(gt_cea, sub_cea, find_func)
        cta_metrics = evaluate_subsumption(
            gt_cta, sub_cta, class_ancestors, class_descendants, key_len=2
        )
        cpa_metrics = evaluate_subsumption(
            gt_cpa, sub_cpa, prop_ancestors, prop_descendants, key_len=3
        )

        results["systems"][sys_name] = {
            "cea": cea_metrics,
            "cta": cta_metrics,
            "cpa": cpa_metrics,
        }

        results["category_metrics"][sys_name] = compute_category_metrics(
            cell_results, challenge_categories
        )

    # Compute rankings (sorted by F1, descending)
    for task in ["cea", "cta", "cpa"]:
        ranked = sorted(
            systems,
            key=lambda s: results["systems"][s][task]["f1"],
            reverse=True,
        )
        results["rankings"][f"{task}_f1"] = ranked

    # Write JSON output
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Build and write N-Triples RDF output
    eval_graph = build_ntriples_graph(results, systems, results["rankings"])
    eval_graph.serialize("/app/results.nt", format="nt")

    print("Evaluation complete.")
    print(f"  JSON: /app/results.json")
    print(f"  N-Triples: /app/results.nt")
    for sys_name in systems:
        s = results["systems"][sys_name]
        print(f"\n{sys_name}:")
        for task in ["cea", "cta", "cpa"]:
            m = s[task]
            print(f"  {task.upper()}: P={m['precision']:.4f} R={m['recall']:.4f} F1={m['f1']:.4f}")


if __name__ == "__main__":
    main()
