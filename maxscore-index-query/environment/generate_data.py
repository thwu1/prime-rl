#!/usr/bin/env python3
"""Generate binary inverted index with VByte-encoded frequencies,
SQLite metadata store, qrels, and deployment artifacts."""

import struct
import random
import math
import os
import sqlite3


def vbyte_encode(value):
    """Encode a single unsigned integer using Variable Byte encoding.
    7 data bits per byte; MSB=1 signals the final byte."""
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value == 0:
            result.append(byte | 0x80)
            break
        result.append(byte)
    return bytes(result)


def bm25(tf, df, dl, avgdl, N, k1, b):
    """BM25 score for a single term-document pair."""
    idf = math.log((N + 1.0) / (df + 0.5))
    tf_norm = (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * dl / avgdl))
    return idf * tf_norm


def main():
    random.seed(20240315)

    NUM_DOCS = 8000
    NUM_TERMS = 3000
    K1 = 0.9
    B = 0.4
    TOP_K = 10

    doc_sizes = []
    for _ in range(NUM_DOCS):
        size = int(random.lognormvariate(4.2, 0.7))
        size = max(10, min(size, 1500))
        doc_sizes.append(size)

    avg_dl = sum(doc_sizes) / NUM_DOCS

    posting_lists = []
    total_postings = 0
    for t in range(NUM_TERMS):
        rank = t + 1
        raw_df = int(NUM_DOCS * 0.4 / rank ** 0.55)
        df = max(1, min(raw_df, NUM_DOCS - 1))
        docs = sorted(random.sample(range(NUM_DOCS), df))
        freqs = []
        for d in docs:
            max_tf = max(1, doc_sizes[d] // 20)
            tf = random.randint(1, max_tf)
            freqs.append(tf)
        posting_lists.append((docs, freqs))
        total_postings += df

    for d in ['/app/index', '/app/logs', '/app/qrels']:
        os.makedirs(d, exist_ok=True)

    # Write .docs: header [1, N] then per-term [len, doc0, doc1, ...]
    with open('/app/index/collection.docs', 'wb') as f:
        f.write(struct.pack('<I', 1))
        f.write(struct.pack('<I', NUM_DOCS))
        for dl, _ in posting_lists:
            f.write(struct.pack('<I', len(dl)))
            for d in dl:
                f.write(struct.pack('<I', d))

    # Write .freqs in VByte encoding: per-term [vbyte(len), vbyte(freq0), ...]
    with open('/app/index/collection.freqs', 'wb') as f:
        for _, fl in posting_lists:
            f.write(vbyte_encode(len(fl)))
            for freq in fl:
                f.write(vbyte_encode(freq))

    # Write .sizes: [N, size0, size1, ...]
    with open('/app/index/collection.sizes', 'wb') as f:
        f.write(struct.pack('<I', NUM_DOCS))
        for s in doc_sizes:
            f.write(struct.pack('<I', s))

    # Create SQLite metadata database
    db = sqlite3.connect('/app/metadata.db')
    cur = db.cursor()

    cur.execute('CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)')
    cur.executemany('INSERT INTO config VALUES (?, ?)', [
        ('k1', str(K1)),
        ('b', str(B)),
        ('top_k', str(TOP_K)),
        ('scoring_model', 'bm25'),
        ('idf_formula', 'ln((N + 1) / (df + 0.5))'),
    ])

    cur.execute(
        'CREATE TABLE terms '
        '(term_id INTEGER PRIMARY KEY, term TEXT NOT NULL, '
        'df INTEGER NOT NULL, cf INTEGER NOT NULL)'
    )
    for t in range(NUM_TERMS):
        term_text = "t%04d" % t
        docs, freqs = posting_lists[t]
        df = len(docs)
        cf = sum(freqs)
        cur.execute('INSERT INTO terms VALUES (?, ?, ?, ?)',
                    (t, term_text, df, cf))

    cur.execute(
        'CREATE TABLE documents '
        '(doc_id INTEGER PRIMARY KEY, external_id TEXT NOT NULL)'
    )
    for d in range(NUM_DOCS):
        ext_id = "DOC-%05d" % d
        cur.execute('INSERT INTO documents VALUES (?, ?)', (d, ext_id))

    db.commit()
    db.close()

    # Write queries
    queries = [
        "Q1:t0003 t0050 t0500",
        "Q2:t0001 t0010 t0020",
        "Q3:t0005 t0015 t0100 t0300",
        "Q4:t0002 t0008 t0030 t0200 t0700",
        "Q5:t0000 t0001 t0002",
        "Q6:t0100 t0400 t0900 t1500 t2500",
        "Q7:t0012 t0045",
        "Q8:t0007 t0025 t0080 t0150 t0500 t1000",
    ]
    with open('/app/queries.txt', 'w') as f:
        for q in queries:
            f.write(q + '\n')

    # Generate qrels with controlled noise so NDCG != 1.0
    term_to_id = {}
    for t in range(NUM_TERMS):
        term_to_id["t%04d" % t] = t

    qrel_rng = random.Random(42)
    qrels_lines = []

    for q_str in queries:
        qid, terms_str = q_str.split(':', 1)
        tnames = terms_str.strip().split()
        tids = [term_to_id[t] for t in tnames]

        scores = {}
        for tid in tids:
            docs, freqs = posting_lists[tid]
            df_val = len(docs)
            for i in range(len(docs)):
                d = docs[i]
                s = bm25(freqs[i], df_val, doc_sizes[d], avg_dl,
                         NUM_DOCS, K1, B)
                scores[d] = scores.get(d, 0.0) + s

        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))

        for rnk, (did, _) in enumerate(ranked[:20]):
            ext_id = "DOC-%05d" % did
            noise = qrel_rng.uniform(0.5, 1.5)
            noisy_rank = rnk * noise
            if noisy_rank < 2.5:
                rel = 3
            elif noisy_rank < 6:
                rel = 2
            elif noisy_rank < 14:
                rel = 1
            else:
                rel = 0
            qrels_lines.append("%s 0 %s %d" % (qid, ext_id, rel))

    with open('/app/qrels/eval.qrels', 'w') as f:
        f.write('\n'.join(qrels_lines) + '\n')

    # Write error log from previous failed evaluation
    docs_sz = os.path.getsize('/app/index/collection.docs')
    freqs_sz = os.path.getsize('/app/index/collection.freqs')
    sizes_sz = os.path.getsize('/app/index/collection.sizes')

    log_lines = [
        "[2024-03-15 14:23:01] Loading index: /app/index/collection",
        "[2024-03-15 14:23:01]   .docs=%dB .freqs=%dB .sizes=%dB"
        % (docs_sz, freqs_sz, sizes_sz),
        "[2024-03-15 14:23:02] Parsed .docs: %d docs, %d terms"
        % (NUM_DOCS, NUM_TERMS),
        "[2024-03-15 14:23:02] WARN: .freqs read error at offset 0 — "
        "expected uint32 length prefix, byte alignment mismatch",
        "[2024-03-15 14:23:02] WARN: .freqs file size (%d) inconsistent "
        "with fixed-width uint32 sequences" % freqs_sz,
        "[2024-03-15 14:23:03] ERROR: Frequency decoding failed — "
        "encoding format differs from .docs",
        "[2024-03-15 14:23:10] Processing skipped — "
        "cannot score without valid frequencies",
        "[2024-03-15 14:23:10] Pipeline terminated.",
    ]
    with open('/app/logs/eval_error.log', 'w') as f:
        f.write('\n'.join(log_lines) + '\n')


if __name__ == '__main__':
    main()
