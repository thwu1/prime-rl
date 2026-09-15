#!/usr/bin/env python3
"""Semantic similarity computation for HPO terms.

Computes Information Content and pairwise/set-level similarity
using pre-built SQLite database from the ontology pipeline.
"""
import sqlite3
import math
import sys
import json
import argparse


def load_config():
    with open("/app/pipeline/config.json") as f:
        return json.load(f)


def get_all_ancestors(conn):
    """Load ancestor sets for all terms from the database."""
    ancestors = {}
    for row in conn.execute("SELECT DISTINCT term_id FROM ancestors"):
        term = row[0]
        ancs = set()
        for r in conn.execute(
            "SELECT ancestor_id FROM ancestors WHERE term_id = ?", (term,)
        ):
            ancs.add(r[0])
        ancestors[term] = frozenset(ancs)
    return ancestors


def compute_ic(conn, ancestors):
    """Compute IC for all terms.

    IC(t) = -ln(freq) where freq = diseases_annotating_t / total_diseases.
    Annotations are propagated upward through the ancestor relation.
    """
    # Collect disease -> term mappings
    diseases = {}
    for row in conn.execute("SELECT disease_id, hpo_id FROM annotations"):
        diseases.setdefault(row[0], set()).add(row[1])

    total = len(diseases)
    if total == 0:
        return {}

    # Propagate annotations upward
    term_disease_count = {}
    for disease_id, terms in diseases.items():
        expanded = set()
        for term in terms:
            if term in ancestors:
                expanded |= ancestors[term]
        for anc in expanded:
            term_disease_count.setdefault(anc, set()).add(disease_id)

    # Compute IC
    ic = {}
    for row in conn.execute("SELECT id FROM terms"):
        term = row[0]
        count = len(term_disease_count.get(term, set()))
        if count == 0:
            ic[term] = 0.0
        else:
            ic[term] = -math.log(count / total)

    return ic


# ---------------------------------------------------------------------------
# Pairwise similarity methods
# ---------------------------------------------------------------------------

def resnik(t1, t2, ancestors, ic):
    """IC of the Most Informative Common Ancestor."""
    a1 = ancestors.get(t1, frozenset())
    a2 = ancestors.get(t2, frozenset())
    common = a1 & a2
    if not common:
        return 0.0
    return max(ic.get(t, 0.0) for t in common)


def lin(t1, t2, ancestors, ic):
    """Lin similarity — normalized MICA IC."""
    r = resnik(t1, t2, ancestors, ic)
    denom = ic.get(t1, 0.0) + ic.get(t2, 0.0)
    if denom == 0.0:
        return 0.0
    return r / denom


def jc(t1, t2, ancestors, ic):
    """Jiang-Conrath distance converted to similarity."""
    if t1 == t2:
        return 1.0
    r = resnik(t1, t2, ancestors, ic)
    ic1 = ic.get(t1, 0.0)
    ic2 = ic.get(t2, 0.0)
    return 1.0 / (ic1 + ic2 - r + 1.0)


def graphic(t1, t2, ancestors, ic):
    """Graph-based IC similarity."""
    if t1 == t2:
        return 1.0
    a1 = ancestors.get(t1, frozenset())
    a2 = ancestors.get(t2, frozenset())
    if not a1 or not a2:
        return 0.0
    common = a1 & a2
    union = a1 | a2
    if len(union) == 0:
        return 0.0
    return len(common) / len(union)


METHODS = {
    "resnik": resnik,
    "lin": lin,
    "jc": jc,
    "graphic": graphic,
}


# ---------------------------------------------------------------------------
# Set-level combiners
# ---------------------------------------------------------------------------

def set_similarity(query_terms, disease_terms, method_name, combiner,
                   ancestors, ic):
    """Compute set-level similarity between a query and disease term set."""
    method = METHODS[method_name]
    q = list(query_terms)
    d = list(disease_terms)
    if not q or not d:
        return 0.0

    # Build pairwise similarity matrix
    matrix = [[method(qi, dj, ancestors, ic) for dj in d] for qi in q]

    row_maxes = [max(row) for row in matrix]
    col_maxes = [max(matrix[r][c] for r in range(len(q))) for c in range(len(d))]

    if combiner == "funsimavg":
        avg_row = sum(row_maxes) / len(q)
        avg_col = sum(col_maxes) / len(d)
        return (avg_row + avg_col) / 2.0
    elif combiner == "funsimmax":
        raise NotImplementedError("funSimMax combiner not yet implemented")
    elif combiner == "bma":
        raise NotImplementedError("BMA combiner not yet implemented")
    else:
        raise ValueError(f"Unknown combiner: {combiner}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    config = load_config()
    db_path = config["database_path"]

    parser = argparse.ArgumentParser(
        description="HPO similarity query engine"
    )
    parser.add_argument("--db", default=db_path,
                        help="Path to SQLite database")
    subparsers = parser.add_subparsers(dest="command")

    ic_p = subparsers.add_parser("ic", help="Information content of a term")
    ic_p.add_argument("term", help="HPO term ID")

    sim_p = subparsers.add_parser("similarity",
                                   help="Pairwise similarity")
    sim_p.add_argument("term1", help="First HPO term ID")
    sim_p.add_argument("term2", help="Second HPO term ID")
    sim_p.add_argument("method", choices=list(METHODS.keys()),
                       help="Similarity method")

    rank_p = subparsers.add_parser("rank", help="Rank diseases")
    rank_p.add_argument("query", help="Comma-separated HPO term IDs")
    rank_p.add_argument("--method", required=True,
                        choices=list(METHODS.keys()))
    rank_p.add_argument("--combiner", required=True,
                        choices=["funsimavg", "funsimmax", "bma"])

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    ancestors = get_all_ancestors(conn)
    ic_values = compute_ic(conn, ancestors)

    if args.command == "ic":
        val = ic_values.get(args.term, 0.0)
        print(f"{val:.6f}")

    elif args.command == "similarity":
        fn = METHODS[args.method]
        score = fn(args.term1, args.term2, ancestors, ic_values)
        print(f"{score:.6f}")

    elif args.command == "rank":
        query_terms = [t.strip() for t in args.query.split(",")]
        diseases = {}
        for row in conn.execute(
            "SELECT disease_id, disease_name, hpo_id FROM annotations"
        ):
            d = diseases.setdefault(row[0], {"name": row[1], "terms": set()})
            d["terms"].add(row[2])

        results = []
        for did, info in diseases.items():
            score = set_similarity(
                query_terms, info["terms"],
                args.method, args.combiner,
                ancestors, ic_values
            )
            results.append((did, info["name"], score))

        results.sort(key=lambda x: (-x[2], x[0]))
        for rank, (did, name, score) in enumerate(results, 1):
            print(f"{rank}\t{did}\t{name}\t{score:.6f}")

    conn.close()


if __name__ == "__main__":
    main()
