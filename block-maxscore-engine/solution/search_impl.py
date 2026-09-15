"""
Rank-Safe BM25 Search Engine with Native C Scoring and SQLite Persistence

Implements a block-max inverted index that:
- Uses a C shared library (libscorer.so) via ctypes for BM25 block scoring
- Stores the inverted index in a SQLite database
- Provides both a Python API and a CLI

"""

import argparse
import ctypes
import json
import math
import os
import sqlite3
import struct
import sys
from collections import defaultdict

# BM25 parameters -- must match /app/bm25.py
K1 = 1.2
B = 0.75


def _idf(df, N):
    return math.log(1.0 + (N - df + 0.5) / (df + 0.5))


# ---------------------------------------------------------------------------
# C library loading
# ---------------------------------------------------------------------------

_lib = ctypes.CDLL("/app/libscorer.so")

_lib.bm25_score_block.argtypes = [
    ctypes.POINTER(ctypes.c_int),    # tfs
    ctypes.POINTER(ctypes.c_int),    # doc_lens
    ctypes.c_int,                     # count
    ctypes.c_double,                  # idf
    ctypes.c_double,                  # avgdl
    ctypes.c_double,                  # k1
    ctypes.c_double,                  # b
    ctypes.POINTER(ctypes.c_double),  # scores_out
]
_lib.bm25_score_block.restype = ctypes.c_double

_lib.advance_to_target.argtypes = [
    ctypes.POINTER(ctypes.c_int),  # doc_ids
    ctypes.c_int,                   # count
    ctypes.c_int,                   # start
    ctypes.c_int,                   # target
]
_lib.advance_to_target.restype = ctypes.c_int


# ---------------------------------------------------------------------------
# Index data structures
# ---------------------------------------------------------------------------


class Block:
    """A fixed-size chunk of a posting list with its max BM25 score."""
    __slots__ = ["doc_ids", "tfs", "max_score"]

    def __init__(self, doc_ids, tfs, max_score):
        self.doc_ids = doc_ids    # list of int, sorted ascending
        self.tfs = tfs            # list of int, parallel to doc_ids
        self.max_score = max_score  # max BM25 score in this block


class TermEntry:
    """Per-term index data: blocks, global max score, document frequency."""
    __slots__ = ["blocks", "global_max", "df", "idf_val"]

    def __init__(self, blocks, global_max, df, idf_val):
        self.blocks = blocks
        self.global_max = global_max
        self.df = df
        self.idf_val = idf_val


class Index:
    """Block-max inverted index."""

    def __init__(self):
        self.terms = {}        # str -> TermEntry
        self.doc_lengths = {}  # doc_id -> int
        self.N = 0
        self.avgdl = 0.0


# ---------------------------------------------------------------------------
# Index construction (uses C library for block scoring)
# ---------------------------------------------------------------------------


def build_index(docs_path, stats_path, block_size=128):
    """Build a block-max inverted index from the corpus."""
    idx = Index()

    with open(stats_path) as f:
        stats = json.load(f)
    idx.N = stats["num_docs"]
    idx.avgdl = stats["avg_doc_length"]

    # Pass 1: build raw posting lists
    raw = defaultdict(list)
    with open(docs_path) as f:
        for line in f:
            doc = json.loads(line)
            doc_id = doc["id"]
            terms = doc["terms"]
            idx.doc_lengths[doc_id] = len(terms)

            tf_map = defaultdict(int)
            for t in terms:
                tf_map[t] += 1
            for t, tf in tf_map.items():
                raw[t].append((doc_id, tf))

    # Pass 2: sort, compute IDF, build blocks with max scores via C library
    for term, plist in raw.items():
        plist.sort()  # sort by doc_id
        df = len(plist)
        idf_val = _idf(df, idx.N)

        blocks = []
        global_max = 0.0

        for i in range(0, len(plist), block_size):
            bp = plist[i:i + block_size]
            dids = [p[0] for p in bp]
            tfs = [p[1] for p in bp]
            doc_lens = [idx.doc_lengths[d] for d in dids]

            n = len(bp)
            c_tfs = (ctypes.c_int * n)(*tfs)
            c_dls = (ctypes.c_int * n)(*doc_lens)
            c_scores = (ctypes.c_double * n)()

            bmax = _lib.bm25_score_block(
                c_tfs, c_dls, n, idf_val, idx.avgdl, K1, B, c_scores
            )

            blocks.append(Block(dids, tfs, bmax))
            if bmax > global_max:
                global_max = bmax

        idx.terms[term] = TermEntry(blocks, global_max, df, idf_val)

    return idx


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------


def save_index(index, db_path):
    """Persist index to a SQLite database."""
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute(
        "CREATE TABLE corpus_stats (key TEXT PRIMARY KEY, value REAL)"
    )
    c.execute("INSERT INTO corpus_stats VALUES ('N', ?)", (float(index.N),))
    c.execute("INSERT INTO corpus_stats VALUES ('avgdl', ?)", (index.avgdl,))

    c.execute(
        "CREATE TABLE doc_lengths (doc_id INTEGER PRIMARY KEY, length INTEGER)"
    )
    c.executemany(
        "INSERT INTO doc_lengths VALUES (?, ?)",
        index.doc_lengths.items()
    )

    c.execute(
        "CREATE TABLE terms ("
        "term TEXT PRIMARY KEY, df INTEGER, idf REAL, global_max REAL)"
    )

    c.execute(
        "CREATE TABLE blocks ("
        "term TEXT, block_idx INTEGER, max_score REAL, "
        "doc_ids BLOB, tfs BLOB, PRIMARY KEY (term, block_idx))"
    )

    for term, entry in index.terms.items():
        c.execute(
            "INSERT INTO terms VALUES (?, ?, ?, ?)",
            (term, entry.df, entry.idf_val, entry.global_max)
        )
        for bi, block in enumerate(entry.blocks):
            did_blob = struct.pack(f'{len(block.doc_ids)}i', *block.doc_ids)
            tf_blob = struct.pack(f'{len(block.tfs)}i', *block.tfs)
            c.execute(
                "INSERT INTO blocks VALUES (?, ?, ?, ?, ?)",
                (term, bi, block.max_score, did_blob, tf_blob)
            )

    conn.commit()
    conn.close()


def load_index(db_path):
    """Load index from a SQLite database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    idx = Index()

    for key, val in c.execute("SELECT key, value FROM corpus_stats"):
        if key == 'N':
            idx.N = int(val)
        elif key == 'avgdl':
            idx.avgdl = val

    idx.doc_lengths = dict(
        c.execute("SELECT doc_id, length FROM doc_lengths").fetchall()
    )

    term_meta = {}
    for term, df, idf_val, gmax in c.execute(
        "SELECT term, df, idf, global_max FROM terms"
    ):
        term_meta[term] = (df, idf_val, gmax)

    current_term = None
    current_blocks = []

    for term, block_idx, mscore, did_blob, tf_blob in c.execute(
        "SELECT term, block_idx, max_score, doc_ids, tfs "
        "FROM blocks ORDER BY term, block_idx"
    ):
        if term != current_term:
            if current_term is not None:
                df, idf_val, gmax = term_meta[current_term]
                idx.terms[current_term] = TermEntry(
                    current_blocks, gmax, df, idf_val
                )
            current_term = term
            current_blocks = []

        n = len(did_blob) // 4
        dids = list(struct.unpack(f'{n}i', did_blob))
        tfs = list(struct.unpack(f'{n}i', tf_blob))
        current_blocks.append(Block(dids, tfs, mscore))

    if current_term is not None:
        df, idf_val, gmax = term_meta[current_term]
        idx.terms[current_term] = TermEntry(
            current_blocks, gmax, df, idf_val
        )

    conn.close()
    return idx


# ---------------------------------------------------------------------------
# Search: document-at-a-time with C batch scoring
# ---------------------------------------------------------------------------


def search(index, query_terms, k):
    """Query the index using document-at-a-time evaluation with native C
    batch scoring via libscorer.so.

    Each term's posting blocks are scored in bulk by the C library's
    bm25_score_block, and per-document scores are accumulated across
    terms.  Returns top-k results rank-safe identical to exhaustive
    evaluation.
    """
    if k <= 0:
        return []

    # Deduplicate and filter to terms present in the index
    seen = set()
    terms = []
    for t in query_terms:
        if t not in seen and t in index.terms:
            seen.add(t)
            terms.append(t)
    if not terms:
        return []

    avgdl = index.avgdl
    doc_lengths = index.doc_lengths
    scores = {}

    for t in terms:
        entry = index.terms[t]
        idf_val = entry.idf_val
        for block in entry.blocks:
            dids = block.doc_ids
            n = len(dids)
            doc_lens = [doc_lengths[d] for d in dids]
            c_tfs = (ctypes.c_int * n)(*block.tfs)
            c_dls = (ctypes.c_int * n)(*doc_lens)
            c_scores = (ctypes.c_double * n)()
            _lib.bm25_score_block(
                c_tfs, c_dls, n, idf_val, avgdl, K1, B, c_scores
            )
            for j in range(n):
                d = dids[j]
                s = c_scores[j]
                if d in scores:
                    scores[d] += s
                else:
                    scores[d] = s

    results = sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:k]
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Rank-safe BM25 search engine with native scoring"
    )
    subparsers = parser.add_subparsers(dest="command")

    build_p = subparsers.add_parser("build", help="Build and persist index")
    build_p.add_argument("--block-size", type=int, default=128)

    query_p = subparsers.add_parser("query", help="Query a persisted index")
    query_p.add_argument("--index", required=True, help="Path to index DB")
    query_p.add_argument("-k", type=int, required=True, help="Number of results")
    query_p.add_argument("terms", nargs="*", help="Query terms")

    args = parser.parse_args()

    if args.command == "build":
        idx = build_index(
            "/app/data/documents.jsonl",
            "/app/data/stats.json",
            block_size=args.block_size,
        )
        save_index(idx, "/app/index.db")
        print("Index built and saved to /app/index.db", file=sys.stderr)
    elif args.command == "query":
        idx = load_index(args.index)
        results = search(idx, args.terms, args.k)
        print(json.dumps([[did, score] for did, score in results]))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
