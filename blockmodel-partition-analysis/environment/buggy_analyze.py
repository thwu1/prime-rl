#!/usr/bin/env python3
"""Main analysis script for partition evaluation."""
import json
import os
import sys
sys.path.insert(0, '/app/pipeline')
from metrics import (load_graph, load_partition, compute_description_length,
                     compute_accuracy, compute_ari, compute_nmi)

GRAPH_PATH = '/app/data/network.tsv'
TRUTH_PATH = '/app/data/ground_truth.tsv'
DETECTIONS_DIR = '/app/data/detections'
OUTPUT_PATH = '/app/results.json'

CANDIDATES = ['A', 'B', 'C', 'D', 'E', 'F']


def main():
    edges = load_graph(GRAPH_PATH)
    truth = load_partition(TRUTH_PATH)
    N = len(truth)

    desc_lengths = {}
    desc_lengths['truth'] = compute_description_length(edges, truth, N)

    candidates = {}
    for c in CANDIDATES:
        path = os.path.join(DETECTIONS_DIR, 'result_{}.tsv'.format(c))
        part = load_partition(path)
        candidates[c] = part
        desc_lengths[c] = compute_description_length(edges, part, N)

    cand_lengths = {c: desc_lengths[c] for c in CANDIDATES}
    best = min(cand_lengths, key=cand_lengths.get)
    ranking = sorted(CANDIDATES, key=lambda c: cand_lengths[c])

    comparison = {}
    for c in CANDIDATES:
        comparison[c] = {
            'accuracy': compute_accuracy(truth, candidates[c]),
            'ari': compute_ari(truth, candidates[c]),
            'nmi': compute_nmi(truth, candidates[c]),
        }

    results = {
        'description_lengths': desc_lengths,
        'best_partition': best,
        'ranking': ranking,
        'comparison_metrics': comparison,
    }

    with open(OUTPUT_PATH, 'w') as f:
        json.dump(results, f, indent=2)

    print('Results written to', OUTPUT_PATH)


if __name__ == '__main__':
    main()
