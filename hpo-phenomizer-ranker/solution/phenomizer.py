#!/usr/bin/env python3
"""HPO Phenotype-Disease Ranking Engine.

Parses HPO ontology (OBO format) and phenotype annotations,
computes Information Content, pairwise semantic similarity,
and ranks diseases by set-level similarity to a query phenotype profile.
"""


import sys
import math
import argparse
from collections import defaultdict

OBO_PATH = "/app/data/ontology.obo"
ANNOT_PATH = "/app/data/annotations.hpoa"


def parse_obo(path):
    """Parse OBO file into term data structures.

    Returns:
        terms: dict {term_id: term_name}
        parents: dict {term_id: [parent_ids]}
        alt_ids: dict {alt_id: primary_id}
    """
    terms = {}
    parents = defaultdict(list)
    alt_ids = {}

    current_id = None
    current_name = None
    current_alts = []
    current_parents = []
    is_obsolete = False
    in_term = False

    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            stripped = line.strip()

            if stripped == "[Term]":
                if in_term and current_id and not is_obsolete:
                    terms[current_id] = current_name or ""
                    parents[current_id] = current_parents
                    for alt in current_alts:
                        alt_ids[alt] = current_id
                in_term = True
                current_id = None
                current_name = None
                current_alts = []
                current_parents = []
                is_obsolete = False
            elif stripped.startswith("[") and stripped.endswith("]"):
                if in_term and current_id and not is_obsolete:
                    terms[current_id] = current_name or ""
                    parents[current_id] = current_parents
                    for alt in current_alts:
                        alt_ids[alt] = current_id
                in_term = False
            elif in_term:
                if stripped.startswith("id: "):
                    current_id = stripped[4:].strip()
                elif stripped.startswith("name: "):
                    current_name = stripped[6:].strip()
                elif stripped.startswith("alt_id: "):
                    current_alts.append(stripped[8:].strip())
                elif stripped.startswith("is_a: "):
                    parent = stripped[6:].split("!")[0].strip()
                    current_parents.append(parent)
                elif stripped == "is_obsolete: true":
                    is_obsolete = True

    # Handle last term in file
    if in_term and current_id and not is_obsolete:
        terms[current_id] = current_name or ""
        parents[current_id] = current_parents
        for alt in current_alts:
            alt_ids[alt] = current_id

    return terms, parents, alt_ids


def compute_all_ancestors(terms, parents):
    """Compute transitive ancestors (including self) for each term.

    Returns dict {term_id: frozenset of ancestor term_ids}.
    """
    cache = {}

    def _ancestors(term):
        if term in cache:
            return cache[term]
        result = {term}
        for parent in parents.get(term, []):
            if parent in terms:
                result |= _ancestors(parent)
        cache[term] = frozenset(result)
        return cache[term]

    for term in terms:
        _ancestors(term)

    return cache


def parse_annotations(path, alt_ids, valid_terms):
    """Parse phenotype annotation file.

    Filters to Aspect=P and Qualifier!=NOT.
    Resolves alt_ids to primary IDs.

    Returns dict {disease_id: {"name": str, "terms": set of term_ids}}.
    """
    diseases = defaultdict(lambda: {"name": "", "terms": set()})

    with open(path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 12:
                continue
            if parts[0] == "DatabaseID":
                continue

            disease_id = parts[0]
            disease_name = parts[1]
            qualifier = parts[2].strip()
            hpo_id = parts[3].strip()
            aspect = parts[10].strip()

            if aspect != "P":
                continue
            if qualifier == "NOT":
                continue

            # Resolve alt_id
            hpo_id = alt_ids.get(hpo_id, hpo_id)

            # Only include terms that exist in the ontology
            if hpo_id not in valid_terms:
                continue

            diseases[disease_id]["name"] = disease_name
            diseases[disease_id]["terms"].add(hpo_id)

    return dict(diseases)


def compute_ic(terms, ancestors, diseases):
    """Compute Information Content for each term.

    IC(term) = -ln(count / total_diseases)
    where count = number of diseases annotating term (after propagation).
    """
    term_disease_count = defaultdict(set)

    for disease_id, info in diseases.items():
        for term in info["terms"]:
            if term in ancestors:
                for ancestor in ancestors[term]:
                    term_disease_count[ancestor].add(disease_id)

    total = len(diseases)
    ic = {}
    for term in terms:
        count = len(term_disease_count.get(term, set()))
        if count == 0 or total == 0:
            ic[term] = 0.0
        else:
            ic[term] = -math.log(count / total)

    return ic


def resnik(t1, t2, ancestors, ic):
    """Resnik similarity: IC of MICA."""
    if t1 not in ancestors or t2 not in ancestors:
        return 0.0
    common = ancestors[t1] & ancestors[t2]
    if not common:
        return 0.0
    return max(ic.get(t, 0.0) for t in common)


def lin(t1, t2, ancestors, ic):
    """Lin similarity: 2*resnik / (IC(a) + IC(b))."""
    r = resnik(t1, t2, ancestors, ic)
    denom = ic.get(t1, 0.0) + ic.get(t2, 0.0)
    if denom == 0.0:
        return 0.0
    return 2.0 * r / denom


def jc(t1, t2, ancestors, ic):
    """Jiang-Conrath similarity: 1 / (IC(a) + IC(b) - 2*resnik + 1)."""
    if t1 == t2:
        return 1.0
    r = resnik(t1, t2, ancestors, ic)
    ic1 = ic.get(t1, 0.0)
    ic2 = ic.get(t2, 0.0)
    return 1.0 / (ic1 + ic2 - 2.0 * r + 1.0)


def graphic(t1, t2, ancestors, ic):
    """GraphIC: sum(IC common ancestors) / sum(IC union ancestors)."""
    if t1 == t2:
        return 1.0
    if t1 not in ancestors or t2 not in ancestors:
        return 0.0
    common = ancestors[t1] & ancestors[t2]
    union = ancestors[t1] | ancestors[t2]
    ic_union = sum(ic.get(t, 0.0) for t in union)
    if ic_union == 0.0:
        return 0.0
    ic_common = sum(ic.get(t, 0.0) for t in common)
    return ic_common / ic_union


METHODS = {
    "resnik": resnik,
    "lin": lin,
    "jc": jc,
    "graphic": graphic,
}


def compute_set_similarity(query_terms, disease_terms, method_name, combiner_name,
                           ancestors, ic_values):
    """Compute set-level similarity between query and disease term sets."""
    method = METHODS[method_name]

    q = list(query_terms)
    d = list(disease_terms)
    rows = len(q)
    cols = len(d)

    if rows == 0 or cols == 0:
        return 0.0

    # Build similarity matrix
    matrix = []
    for qi in q:
        row = [method(qi, dj, ancestors, ic_values) for dj in d]
        matrix.append(row)

    # Row maxima
    row_maxes = [max(row) for row in matrix]

    # Column maxima
    col_maxes = []
    for c in range(cols):
        col_maxes.append(max(matrix[r][c] for r in range(rows)))

    if combiner_name == "funsimavg":
        avg_row = sum(row_maxes) / rows
        avg_col = sum(col_maxes) / cols
        return (avg_row + avg_col) / 2.0
    elif combiner_name == "funsimmax":
        avg_row = sum(row_maxes) / rows
        avg_col = sum(col_maxes) / cols
        return max(avg_row, avg_col)
    elif combiner_name == "bma":
        return (sum(row_maxes) + sum(col_maxes)) / (rows + cols)
    else:
        raise ValueError(f"Unknown combiner: {combiner_name}")


def load_all():
    """Load and precompute all data structures."""
    terms, parents, alt_ids = parse_obo(OBO_PATH)
    ancestors = compute_all_ancestors(terms, parents)
    diseases = parse_annotations(ANNOT_PATH, alt_ids, terms)
    ic_values = compute_ic(terms, ancestors, diseases)
    return terms, parents, alt_ids, ancestors, diseases, ic_values


def main():
    parser = argparse.ArgumentParser(
        description="HPO Phenotype-Disease Ranking Engine"
    )
    subparsers = parser.add_subparsers(dest="command")

    ic_parser = subparsers.add_parser("ic", help="Compute IC for a term")
    ic_parser.add_argument("term", help="HPO term ID")

    sim_parser = subparsers.add_parser("similarity",
                                       help="Pairwise similarity")
    sim_parser.add_argument("term1", help="First HPO term ID")
    sim_parser.add_argument("term2", help="Second HPO term ID")
    sim_parser.add_argument("--method", required=True,
                           choices=["resnik", "lin", "jc", "graphic"])

    rank_parser = subparsers.add_parser("rank", help="Rank diseases")
    rank_parser.add_argument("query",
                            help="Comma-separated HPO term IDs")
    rank_parser.add_argument("--method", required=True,
                            choices=["resnik", "lin", "jc", "graphic"])
    rank_parser.add_argument("--combiner", required=True,
                            choices=["funsimavg", "funsimmax", "bma"])

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    terms, parents, alt_ids, ancestors, diseases, ic_values = load_all()

    def resolve(term_id):
        return alt_ids.get(term_id, term_id)

    if args.command == "ic":
        t = resolve(args.term)
        val = ic_values.get(t, 0.0)
        print(f"{val:.6f}")

    elif args.command == "similarity":
        t1 = resolve(args.term1)
        t2 = resolve(args.term2)
        method = METHODS[args.method]
        score = method(t1, t2, ancestors, ic_values)
        print(f"{score:.6f}")

    elif args.command == "rank":
        query_terms = [resolve(t.strip()) for t in args.query.split(",")]

        results = []
        for disease_id, info in diseases.items():
            d_terms = list(info["terms"])
            score = compute_set_similarity(
                query_terms, d_terms,
                args.method, args.combiner,
                ancestors, ic_values,
            )
            results.append((disease_id, info["name"], score))

        results.sort(key=lambda x: (-x[2], x[0]))

        for rank, (did, name, score) in enumerate(results, 1):
            print(f"{rank}\t{did}\t{name}\t{score:.6f}")


if __name__ == "__main__":
    main()
