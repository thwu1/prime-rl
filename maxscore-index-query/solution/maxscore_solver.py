#!/usr/bin/env python3
"""
MaxScore query processor with VByte decoding, SQLite metadata,
TREC run output, and trec_eval evaluation pipeline.
"""


import struct
import json
import math
import heapq
import sqlite3
import subprocess
import re


def vbyte_decode_stream(data):
    """Decode all VByte-encoded integers from bytes.
    7 data bits per byte, MSB=1 is final byte."""
    values = []
    offset = 0
    while offset < len(data):
        value = 0
        shift = 0
        while True:
            byte = data[offset]
            offset += 1
            value |= (byte & 0x7F) << shift
            if byte & 0x80:
                break
            shift += 7
        values.append(value)
    return values


def read_docs(path):
    """Read PISA .docs binary file: header [1, N], then per-term sequences."""
    with open(path, 'rb') as f:
        data = f.read()
    offset = 0
    struct.unpack_from('<I', data, offset)[0]  # header length = 1
    offset += 4
    num_docs = struct.unpack_from('<I', data, offset)[0]
    offset += 4

    posting_docs = []
    while offset < len(data):
        length = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        docs = list(struct.unpack_from('<' + 'I' * length, data, offset))
        offset += 4 * length
        posting_docs.append(docs)
    return num_docs, posting_docs


def read_freqs(path):
    """Read VByte-encoded .freqs file: per-term length-prefixed sequences."""
    with open(path, 'rb') as f:
        data = f.read()
    vbytes = vbyte_decode_stream(data)
    posting_freqs = []
    j = 0
    while j < len(vbytes):
        length = vbytes[j]
        j += 1
        posting_freqs.append(vbytes[j:j + length])
        j += length
    return posting_freqs


def read_sizes(path):
    """Read PISA .sizes binary file: [N, size_0, ..., size_{N-1}]."""
    with open(path, 'rb') as f:
        data = f.read()
    num_docs = struct.unpack_from('<I', data, 0)[0]
    sizes = list(struct.unpack_from('<' + 'I' * num_docs, data, 4))
    return sizes


def bm25_score(tf, df, dl, avgdl, N, k1, b):
    """BM25 score for a single term-document pair."""
    idf = math.log((N + 1.0) / (df + 0.5))
    tf_norm = (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * dl / avgdl))
    return idf * tf_norm


def maxscore_topk(query_tids, posting_docs, posting_freqs,
                  sizes, avgdl, N, k1, b, top_k):
    """MaxScore algorithm for disjunctive top-k BM25 retrieval.
    Returns (results, num_scored)."""
    if not query_tids:
        return [], 0

    terms = []
    for tid in query_tids:
        docs = posting_docs[tid]
        freqs = posting_freqs[tid]
        df = len(docs)
        ub = max(
            bm25_score(freqs[i], df, sizes[docs[i]], avgdl, N, k1, b)
            for i in range(len(docs))
        )
        terms.append({
            'docs': docs, 'freqs': freqs, 'df': df,
            'ub': ub, 'cur': 0
        })

    terms.sort(key=lambda x: x['ub'])
    n = len(terms)

    prefix = [0.0] * (n + 1)
    for i in range(n):
        prefix[i + 1] = prefix[i] + terms[i]['ub']

    heap = []
    theta = 0.0
    num_scored = 0
    ess = 0

    def update_ess():
        nonlocal ess
        ess = 0
        for i in range(1, n + 1):
            if prefix[i] < theta:
                ess = i
            else:
                break

    update_ess()

    while ess < n:
        pivot = None
        for i in range(ess, n):
            t = terms[i]
            if t['cur'] < len(t['docs']):
                d = t['docs'][t['cur']]
                if pivot is None or d < pivot:
                    pivot = d

        if pivot is None:
            break

        score = 0.0
        for i in range(ess, n):
            t = terms[i]
            while t['cur'] < len(t['docs']) and t['docs'][t['cur']] < pivot:
                t['cur'] += 1
            if t['cur'] < len(t['docs']) and t['docs'][t['cur']] == pivot:
                score += bm25_score(
                    t['freqs'][t['cur']], t['df'],
                    sizes[pivot], avgdl, N, k1, b
                )
                t['cur'] += 1

        if score + prefix[ess] > theta:
            for i in range(ess):
                t = terms[i]
                while (t['cur'] < len(t['docs'])
                       and t['docs'][t['cur']] < pivot):
                    t['cur'] += 1
                if (t['cur'] < len(t['docs'])
                        and t['docs'][t['cur']] == pivot):
                    score += bm25_score(
                        t['freqs'][t['cur']], t['df'],
                        sizes[pivot], avgdl, N, k1, b
                    )
                    t['cur'] += 1

            num_scored += 1

            if len(heap) < top_k:
                heapq.heappush(heap, (score, pivot))
                if len(heap) == top_k:
                    theta = heap[0][0]
                    update_ess()
            elif score > theta:
                heapq.heapreplace(heap, (score, pivot))
                theta = heap[0][0]
                update_ess()

    results = sorted(heap, key=lambda x: (-x[0], x[1]))
    return [(did, sc) for sc, did in results], num_scored


def main():
    base = '/app/index/collection'

    # Load index
    num_docs, posting_docs = read_docs(base + '.docs')
    posting_freqs = read_freqs(base + '.freqs')
    sizes = read_sizes(base + '.sizes')

    num_terms = len(posting_docs)
    avg_dl = sum(sizes) / len(sizes)
    total_postings = sum(len(pl) for pl in posting_docs)

    # Load config and mappings from SQLite
    db = sqlite3.connect('/app/metadata.db')
    cur = db.cursor()

    config = {}
    cur.execute('SELECT key, value FROM config')
    for key, value in cur.fetchall():
        config[key] = value
    k1 = float(config['k1'])
    b = float(config['b'])
    top_k = int(float(config['top_k']))

    cur.execute('SELECT term, term_id FROM terms')
    term_to_id = {term: tid for term, tid in cur.fetchall()}

    cur.execute('SELECT doc_id, external_id FROM documents')
    doc_to_ext = {did: ext for did, ext in cur.fetchall()}

    db.close()

    # Load queries
    queries = []
    with open('/app/queries.txt', 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            qid, terms_str = line.split(':', 1)
            tnames = terms_str.strip().split()
            tids = [term_to_id[t] for t in tnames if t in term_to_id]
            queries.append((qid, tids))

    # Process queries with MaxScore
    query_results = []
    run_lines = []

    for qid, tids in queries:
        results, num_scored = maxscore_topk(
            tids, posting_docs, posting_freqs, sizes, avg_dl,
            num_docs, k1, b, top_k
        )
        query_results.append({
            'qid': qid,
            'results': [
                {'docid': did, 'score': round(sc, 6)}
                for did, sc in results
            ],
            'num_scored': num_scored,
        })

        for rank, (did, score) in enumerate(results, 1):
            ext_id = doc_to_ext[did]
            run_lines.append(
                "%s Q0 %s %d %.6f maxscore" % (qid, ext_id, rank, score)
            )

    # Write TREC run file
    with open('/app/results.run', 'w') as f:
        f.write('\n'.join(run_lines) + '\n')

    # Run trec_eval (already compiled by solve.sh)
    result = subprocess.run(
        ['/app/tools/trec_eval/trec_eval',
         '-m', 'ndcg_cut.10', '-m', 'map',
         '/app/qrels/eval.qrels', '/app/results.run'],
        capture_output=True, text=True
    )

    eval_metrics = {}
    for line in result.stdout.strip().split('\n'):
        parts = line.strip().split()
        if len(parts) >= 3 and parts[1] == 'all':
            metric = parts[0]
            value = float(parts[2])
            if metric == 'ndcg_cut_10':
                eval_metrics['ndcg_cut_10'] = round(value, 4)
            elif metric == 'map':
                eval_metrics['map'] = round(value, 4)

    # Write output
    output = {
        'index_stats': {
            'num_docs': num_docs,
            'num_terms': num_terms,
            'avg_doc_len': round(avg_dl, 4),
            'total_postings': total_postings,
        },
        'queries': query_results,
        'eval_metrics': eval_metrics,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print("Processed %d queries over %d docs, %d terms" % (
        len(queries), num_docs, num_terms))
    print("NDCG@10: %s" % eval_metrics.get('ndcg_cut_10', 'N/A'))
    print("MAP: %s" % eval_metrics.get('map', 'N/A'))


if __name__ == '__main__':
    main()
