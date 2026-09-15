#!/usr/bin/env python3
"""
BM25 and Query Likelihood (Dirichlet) batch retrieval over a JSON inverted index.

Usage:
  BM25:  python3 bm25_search.py --index INDEX.json --queries Q.tsv --output RUN.txt [--k1 0.9] [--b 0.4]
  QLD:   python3 bm25_search.py --index INDEX.json --queries Q.tsv --output RUN.txt --qld [--mu 1000]

The index is a JSON file built by the setup script containing postings,
document lengths, and collection statistics. Queries are tab-separated
(qid<TAB>text). Output is in standard TREC run format.
"""

import argparse
import json
import math
import re
import sys
from collections import defaultdict


def tokenize(text):
    """Lowercase alphanumeric tokenizer."""
    return re.findall(r'[a-z0-9]+', text.lower())


def load_index(path):
    """Load JSON inverted index."""
    with open(path) as f:
        return json.load(f)


def load_queries(path):
    """Load TSV queries file (qid<TAB>text)."""
    queries = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t', 1)
            if len(parts) == 2:
                queries.append((parts[0], parts[1]))
    return queries


def search_bm25(index, queries, k1, b, hits):
    """BM25 batch retrieval.

    BM25(d,q) = sum_t IDF(t) * tf(t,d)*(k1+1) / (tf(t,d) + k1*(1-b+b*|d|/avgdl))
    IDF(t) = ln(1 + (N-df(t)+0.5)/(df(t)+0.5))
    """
    N = index['num_docs']
    avgdl = index['avg_doc_length']
    postings = index['postings']
    doc_lengths = index['doc_lengths']
    results = {}

    for qid, qtext in queries:
        scores = defaultdict(float)
        for term in tokenize(qtext):
            if term not in postings:
                continue
            df = len(postings[term])
            idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
            for docid, tf in postings[term].items():
                dl = doc_lengths[docid]
                tf_comp = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
                scores[docid] += idf * tf_comp
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:hits]
        results[qid] = ranked
    return results


def search_qld(index, queries, mu, hits):
    """Query Likelihood with Dirichlet smoothing batch retrieval.

    QLD(d,q) = sum_t ln((tf(t,d) + mu*P(t|C)) / (|d| + mu))
    P(t|C) = cf(t) / total_terms
    """
    postings = index['postings']
    doc_lengths = index['doc_lengths']
    total_terms = index['total_terms']
    coll_freqs = index['collection_freqs']
    results = {}

    for qid, qtext in queries:
        scores = defaultdict(float)
        for term in tokenize(qtext):
            if term not in postings:
                continue
            cf = coll_freqs.get(term, 1)
            p_coll = cf / total_terms
            for docid, tf in postings[term].items():
                dl = doc_lengths[docid]
                scores[docid] += math.log((tf + mu * p_coll) / (dl + mu))
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:hits]
        results[qid] = ranked
    return results


def write_run(results, path, tag='run'):
    """Write results in TREC run format: qid Q0 docid rank score tag"""
    with open(path, 'w') as f:
        for qid in sorted(results.keys(), key=lambda x: int(x) if x.isdigit() else x):
            for rank, (docid, score) in enumerate(results[qid], 1):
                f.write(f"{qid} Q0 {docid} {rank} {score:.6f} {tag}\n")


def main():
    p = argparse.ArgumentParser(
        description='BM25 / QLD batch retrieval over JSON inverted index')
    p.add_argument('--index', required=True, help='JSON inverted index path')
    p.add_argument('--queries', required=True,
                   help='TSV queries file (qid<TAB>text)')
    p.add_argument('--output', required=True, help='Output TREC run file')
    p.add_argument('--k1', type=float, default=0.9,
                   help='BM25 k1 parameter (default: 0.9)')
    p.add_argument('--b', type=float, default=0.4,
                   help='BM25 b parameter (default: 0.4)')
    p.add_argument('--qld', action='store_true',
                   help='Use Query Likelihood with Dirichlet smoothing')
    p.add_argument('--mu', type=float, default=1000.0,
                   help='QLD Dirichlet mu parameter (default: 1000)')
    p.add_argument('--hits', type=int, default=1000,
                   help='Max hits per query (default: 1000)')
    p.add_argument('--tag', default='run',
                   help='Run tag in output (default: run)')
    args = p.parse_args()

    index = load_index(args.index)
    queries = load_queries(args.queries)

    if args.qld:
        results = search_qld(index, queries, args.mu, args.hits)
    else:
        results = search_bm25(index, queries, args.k1, args.b, args.hits)

    write_run(results, args.output, args.tag)


if __name__ == '__main__':
    main()
