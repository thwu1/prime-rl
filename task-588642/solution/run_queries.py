#!/usr/bin/env python3
"""Process fuzzy queries using the parametric Levenshtein DFA.

"""

import json
import os
import sys

sys.path.insert(0, '/app')
from parametric_dfa import LevenshteinParametricDFA


def main():
    # Load dictionary
    with open('/app/dictionary.txt') as f:
        dictionary = [line.strip() for line in f if line.strip()]

    # Load queries
    with open('/app/queries.json') as f:
        queries = json.load(f)

    # Build parametric DFAs (precomputed, query-independent)
    print("Building parametric DFA for D=1...")
    pdfa1 = LevenshteinParametricDFA(1)
    print(f"  -> {pdfa1.num_states()} non-dead states")

    print("Building parametric DFA for D=2...")
    pdfa2 = LevenshteinParametricDFA(2)
    print(f"  -> {pdfa2.num_states()} non-dead states")

    pdfas = {1: pdfa1, 2: pdfa2}

    # Process queries
    results = {"query_results": []}
    for i, q in enumerate(queries):
        query_str = q['query']
        max_d = q['max_distance']
        pdfa = pdfas[max_d]

        print(f"Query {i+1}/{len(queries)}: {query_str!r} (D={max_d})")

        matches = []
        for word in dictionary:
            match, dist = pdfa.eval(query_str, word)
            if match:
                matches.append({"word": word, "distance": dist})

        matches.sort(key=lambda m: (m['distance'], m['word']))
        results['query_results'].append({
            "query": query_str,
            "max_distance": max_d,
            "matches": matches,
        })
        print(f"  -> {len(matches)} matches")

    # Write results
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    # Write DFA stats
    stats = {
        "d1_parametric_states": pdfa1.num_states(),
        "d2_parametric_states": pdfa2.num_states(),
    }
    with open('/app/output/dfa_stats.json', 'w') as f:
        json.dump(stats, f, indent=2)

    print(f"\nDone. Processed {len(queries)} queries against "
          f"{len(dictionary)} dictionary words.")
    print(f"D=1 parametric states: {stats['d1_parametric_states']}")
    print(f"D=2 parametric states: {stats['d2_parametric_states']}")


if __name__ == '__main__':
    main()
