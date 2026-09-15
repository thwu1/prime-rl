#!/usr/bin/env python3
"""Streaming ANN benchmark engine — reference implementation.

Processes a YAML runbook of insert/delete/replace/search operations over
dense float32 vectors stored in BigANN binary (.fbin/.ibin) format.
"""

import argparse
import json
import os

import numpy as np
import yaml


# ── Binary I/O ────────────────────────────────────────────────────────────

def read_fbin(filepath):
    """Read float32 vectors: 8-byte header [uint32 n, uint32 d] + n*d float32."""
    with open(filepath, 'rb') as f:
        header = np.fromfile(f, dtype='uint32', count=2)
        n, d = int(header[0]), int(header[1])
        data = np.fromfile(f, dtype='float32', count=n * d).reshape(n, d)
    return data


def write_fbin(filepath, data):
    n, d = data.shape
    with open(filepath, 'wb') as f:
        np.array([n, d], dtype='uint32').tofile(f)
        data.astype('float32').tofile(f)


def write_ibin(filepath, data):
    n, d = data.shape
    with open(filepath, 'wb') as f:
        np.array([n, d], dtype='uint32').tofile(f)
        data.astype('int32').tofile(f)


# ── k-NN search ───────────────────────────────────────────────────────────

def knn_search(base_data, tag_to_id, queries, k):
    """Brute-force k-NN using squared L2 distance.

    Returns (tag_ids, distances) each of shape (nq, k).
    tag_ids are the external tag identifiers (not base-vector indices).
    """
    tags = sorted(tag_to_id.keys())
    vec_ids = [tag_to_id[t] for t in tags]
    active_vectors = base_data[vec_ids]  # (num_active, d)

    nq = queries.shape[0]
    actual_k = min(k, len(tags))
    result_tags = np.zeros((nq, actual_k), dtype='int32')
    result_dists = np.zeros((nq, actual_k), dtype='float32')

    for qi in range(nq):
        diffs = active_vectors - queries[qi]          # (num_active, d)
        sq_dists = np.sum(diffs * diffs, axis=1)      # (num_active,)
        topk_local = np.argsort(sq_dists)[:actual_k]
        result_tags[qi] = [tags[idx] for idx in topk_local]
        result_dists[qi] = sq_dists[topk_local]

    # Pad with -1 / inf if fewer active points than k
    if actual_k < k:
        pad_tags = np.full((nq, k - actual_k), -1, dtype='int32')
        pad_dists = np.full((nq, k - actual_k), np.inf, dtype='float32')
        result_tags = np.hstack([result_tags, pad_tags])
        result_dists = np.hstack([result_dists, pad_dists])

    return result_tags, result_dists


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Streaming ANN engine')
    parser.add_argument('--base', required=True, help='Path to base vectors (.fbin)')
    parser.add_argument('--queries', required=True, help='Path to query vectors (.fbin)')
    parser.add_argument('--runbook', required=True, help='Path to runbook YAML')
    parser.add_argument('--k', type=int, default=10, help='Number of neighbors')
    parser.add_argument('--output_dir', required=True, help='Output directory')
    args = parser.parse_args()

    base = read_fbin(args.base)
    queries = read_fbin(args.queries)

    with open(args.runbook) as f:
        runbook = yaml.safe_load(f)

    dataset_name = list(runbook.keys())[0]
    entries = runbook[dataset_name]

    os.makedirs(args.output_dir, exist_ok=True)

    tag_to_id = {}
    search_results = []

    step_nums = sorted(k for k in entries.keys() if isinstance(k, int))

    for step_num in step_nums:
        entry = entries[step_num]
        op = entry['operation']

        if op == 'insert':
            for i in range(entry['start'], entry['end']):
                tag_to_id[i] = i

        elif op == 'delete':
            for i in range(entry['start'], entry['end']):
                tag_to_id.pop(i, None)

        elif op == 'replace':
            for i in range(entry['tags_end'] - entry['tags_start']):
                tag = entry['tags_start'] + i
                vec_id = entry['ids_start'] + i
                tag_to_id[tag] = vec_id

        elif op == 'search':
            nb_tags, nb_dists = knn_search(base, tag_to_id, queries, args.k)

            write_ibin(
                os.path.join(args.output_dir, f'step{step_num}_neighbors.ibin'),
                nb_tags,
            )
            write_fbin(
                os.path.join(args.output_dir, f'step{step_num}_distances.fbin'),
                nb_dists,
            )
            search_results.append({
                'step': step_num,
                'num_active_points': len(tag_to_id),
            })

    summary = {'search_steps': search_results}
    with open(os.path.join(args.output_dir, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=2)


if __name__ == '__main__':
    main()
