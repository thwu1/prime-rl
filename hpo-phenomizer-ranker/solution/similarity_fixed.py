#!/usr/bin/env python3
"""Semantic similarity computation for HPO terms.

FIXED version:
- Lin formula has 2x factor
- JC formula has 2x on resnik term
- GraphIC uses IC sums (not term counts)
- funSimMax and BMA combiners implemented
- CLI uses --method flag (not positional)
- Alt_id resolution for annotations and queries
"""

import sqlite3
import math
import sys
import json
import argparse


def load_config():
    with open("/app/pipeline/config.json") as f:
        return json.load(f)


def get_alt_ids(conn):
    """Load alt_id -> primary_id mappings from the database."""
    alt_ids = {}
    for row in conn.execute("SELECT alt_id, primary_id FROM alt_ids"):
        alt_ids[row[0]] = row[1]
    return alt_ids


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


def compute_ic(conn, ancestors, alt_ids):
    """Compute IC for all terms.

    IC(t) = -ln(freq) where freq = diseases_annotating_t / total_diseases.
    Annotations are propagated upward through the ancestor relation.
    """
    # Collect disease -> term mappings, resolving alt_ids
    diseases = {}
    for row in conn.execute("SELECT disease_id, hpo_id FROM annotations"):
        hpo_id = alt_ids.get(row[1], row[1])
        diseases.setdefault(row[0], set()).add(hpo_id)

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
    """Lin similarity: 2 * MICA_IC / (IC(a) + IC(b))."""
    r = resnik(t1, t2, ancestors, ic)
    denom = ic.get(t1, 0.0) + ic.get(t2, 0.0)
    if denom == 0.0:
        return 0.0
    # FIX: Added 2.0 factor
    return 2.0 * r / denom


def jc(t1, t2, ancestors, ic):
    """Jiang-Conrath distance converted to similarity."""
    if t1 == t2:
        return 1.0
    r = resnik(t1, t2, ancestors, ic)
    ic1 = ic.get(t1, 0.0)
    ic2 = ic.get(t2, 0.0)
    # FIX: Use 2.0 * r instead of r
    return 1.0 / (ic1 + ic2 - 2.0 * r + 1.0)


def graphic(t1, t2, ancestors, ic):
    """Graph-based IC similarity: sum IC of shared / sum IC of union."""
    if t1 == t2:
        return 1.0
    a1 = ancestors.get(t1, frozenset())
    a2 = ancestors.get(t2, frozenset())
    if not a1 or not a2:
        return 0.0
    common = a1 & a2
    union = a1 | a2
    # FIX: Use IC sums instead of term counts
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
        # FIX: Implemented (was NotImplementedError)
        avg_row = sum(row_maxes) / len(q)
        avg_col = sum(col_maxes) / len(d)
        return max(avg_row, avg_col)
    elif combiner == "bma":
        # FIX: Implemented (was NotImplementedError)
        return (sum(row_maxes) + sum(col_maxes)) / (len(q) + len(d))
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
    # FIX: Changed from positional to --method flag
    sim_p.add_argument("--method", required=True,
                       choices=list(METHODS.keys()),
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
    alt_ids = get_alt_ids(conn)
    ancestors = get_all_ancestors(conn)
    ic_values = compute_ic(conn, ancestors, alt_ids)

    def resolve(term_id):
        """Resolve alt_id to primary ID."""
        return alt_ids.get(term_id, term_id)

    if args.command == "ic":
        t = resolve(args.term)
        val = ic_values.get(t, 0.0)
        print(f"{val:.6f}")

    elif args.command == "similarity":
        t1 = resolve(args.term1)
        t2 = resolve(args.term2)
        fn = METHODS[args.method]
        score = fn(t1, t2, ancestors, ic_values)
        print(f"{score:.6f}")

    elif args.command == "rank":
        query_terms = [resolve(t.strip()) for t in args.query.split(",")]

        # Build disease term sets, resolving alt_ids
        diseases = {}
        for row in conn.execute(
            "SELECT disease_id, disease_name, hpo_id FROM annotations"
        ):
            hpo_id = alt_ids.get(row[2], row[2])
            d = diseases.setdefault(row[0], {"name": row[1], "terms": set()})
            d["terms"].add(hpo_id)

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
