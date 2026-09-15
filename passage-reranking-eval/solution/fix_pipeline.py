#!/usr/bin/env python3
"""
Correct BM25 reranking pipeline and multi-metric IR evaluation.

Diagnoses bugs in /app/pipeline/, implements a correct BM25 scorer
reading from the SQLite database, and produces all required outputs.
"""


import json
import math
import os
import sqlite3
import subprocess
from collections import Counter, defaultdict

DATA_DIR = "/app/data"
OUT_DIR = "/app/output"
DB_PATH = os.path.join(DATA_DIR, "corpus.db")
QRELS_PATH = os.path.join(DATA_DIR, "qrels.tsv")

os.makedirs(OUT_DIR, exist_ok=True)


# ── Bug report ───────────────────────────────────────────────────────────────

def write_bug_report():
    report = {
        "bugs": [
            {
                "file": "tokenizer.py",
                "description": (
                    "tokenize_query() does not call .lower() on input text, "
                    "causing case mismatch with document tokens that are lowercased "
                    "by tokenize_doc(). Mixed-case query terms like 'Diagnosis' fail "
                    "to match the lowercased passage token 'diagnosis'."
                ),
                "fix": (
                    "Added .lower() in tokenize_query() to ensure queries are "
                    "lowercased the same way as documents."
                )
            },
            {
                "file": "index.py",
                "description": (
                    "build_from_db() queries the candidates table joined with "
                    "collection WITHOUT DISTINCT. Since each passage appears as a "
                    "candidate for multiple queries, document frequencies are inflated "
                    "by roughly 10x, causing IDF values to be severely underestimated "
                    "and even become negative for common terms."
                ),
                "fix": (
                    "Changed SQL to SELECT pid, text FROM collection to index "
                    "the full collection exactly once per passage."
                )
            },
            {
                "file": "bm25.py",
                "description": (
                    "BM25 TF normalization uses avg_dl/dl instead of dl/avg_dl "
                    "in the length normalization factor. This inverts the document "
                    "length penalty: short documents are penalized while long "
                    "documents are boosted, which is the opposite of correct BM25."
                ),
                "fix": (
                    "Changed (1 - b + b * avg_dl / dl) to (1 - b + b * dl / avg_dl) "
                    "in the TF normalization denominator."
                )
            },
            {
                "file": "run_pipeline.py",
                "description": (
                    "enumerate(scored) produces 0-indexed ranks starting from 0. "
                    "The MS MARCO eval script expects 1-indexed ranks and uses "
                    "rank-1 as an array index. With rank=0, rank-1=-1 wraps to the "
                    "end of the array, placing the best result at position 1000."
                ),
                "fix": (
                    "Changed enumerate(scored) to enumerate(scored, 1) to produce "
                    "1-indexed ranks."
                )
            }
        ]
    }
    with open(os.path.join(OUT_DIR, "bug_report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print("Bug report written.")


# ── Correct tokenizer ───────────────────────────────────────────────────────

def tokenize(text):
    """Case-insensitive whitespace tokenizer."""
    return text.lower().split()


# ── Correct BM25 ────────────────────────────────────────────────────────────

class BM25:
    def __init__(self, k1=1.2, b=0.75):
        self.k1 = k1
        self.b = b
        self.N = 0
        self.df = Counter()
        self.doc_lens = {}
        self.avg_dl = 0.0

    def build_index(self, db_path):
        """Build inverted index over the FULL collection from SQLite."""
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT pid, text FROM collection")

        total_len = 0
        for pid, text in c.fetchall():
            tokens = tokenize(text)
            self.doc_lens[pid] = len(tokens)
            total_len += len(tokens)
            self.N += 1
            for term in set(tokens):
                self.df[term] += 1

        self.avg_dl = total_len / self.N if self.N > 0 else 1.0
        conn.close()
        print(f"Index built: N={self.N}, unique_terms={len(self.df)}, "
              f"avg_dl={self.avg_dl:.1f}")

    def idf(self, term):
        n = self.df.get(term, 0)
        return math.log((self.N - n + 0.5) / (n + 0.5) + 1.0)

    def score(self, query_tokens, passage_text, pid):
        p_tokens = tokenize(passage_text)
        dl = self.doc_lens.get(pid, len(p_tokens))

        tf_map = Counter(p_tokens)
        s = 0.0
        for qt in query_tokens:
            if qt not in tf_map:
                continue
            tf = tf_map[qt]
            idf_val = self.idf(qt)
            # Correct BM25: dl / avg_dl (not avg_dl / dl)
            tf_norm = (tf * (self.k1 + 1)) / (
                tf + self.k1 * (1 - self.b + self.b * dl / self.avg_dl)
            )
            s += idf_val * tf_norm
        return s


# ── Metric implementations ──────────────────────────────────────────────────

def compute_mrr_at_k(qrels, run, k=10):
    mrr = 0.0
    for qid, rel_pids in qrels.items():
        if qid not in run:
            continue
        ranked = run[qid]
        for i in range(min(k, len(ranked))):
            if ranked[i] in rel_pids:
                mrr += 1.0 / (i + 1)
                break
    return mrr / len(qrels)


def compute_ndcg_at_k(qrels, run, k=10):
    ndcg_sum = 0.0
    for qid, rel_pids in qrels.items():
        if qid not in run:
            continue
        ranked = run[qid]
        dcg = 0.0
        for i in range(min(k, len(ranked))):
            if ranked[i] in rel_pids:
                dcg += 1.0 / math.log2(i + 2)
        n_rel = len(rel_pids)
        idcg = sum(1.0 / math.log2(j + 2) for j in range(min(n_rel, k)))
        if idcg > 0:
            ndcg_sum += dcg / idcg
    return ndcg_sum / len(qrels)


def compute_map(qrels, run):
    ap_sum = 0.0
    for qid, rel_pids in qrels.items():
        if qid not in run:
            continue
        ranked = run[qid]
        n_rel_found = 0
        ap = 0.0
        for i in range(len(ranked)):
            if ranked[i] in rel_pids:
                n_rel_found += 1
                ap += n_rel_found / (i + 1)
        if len(rel_pids) > 0:
            ap_sum += ap / len(rel_pids)
    return ap_sum / len(qrels)


def compute_recall_at_k(qrels, run, k):
    recall_sum = 0.0
    for qid, rel_pids in qrels.items():
        if qid not in run:
            continue
        ranked = run[qid]
        retrieved = set(ranked[:min(k, len(ranked))])
        recall_sum += len(retrieved & rel_pids) / len(rel_pids)
    return recall_sum / len(qrels)


# ── Data loading ─────────────────────────────────────────────────────────────

def load_qrels():
    qrels = {}
    with open(QRELS_PATH) as f:
        for line in f:
            parts = line.strip().split("\t")
            qid = int(parts[0])
            pid = int(parts[2])
            qrels.setdefault(qid, set()).add(pid)
    return qrels


def load_run(path):
    raw = defaultdict(dict)
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t")
            qid, pid, rank = int(parts[0]), int(parts[1]), int(parts[2])
            raw[qid][rank] = pid
    result = {}
    for qid, rm in raw.items():
        mx = max(rm.keys())
        result[qid] = [rm.get(r, 0) for r in range(1, mx + 1)]
    return result


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Step 1: Write bug report
    write_bug_report()

    # Step 2: Build correct BM25 index from SQLite
    bm25 = BM25(k1=1.2, b=0.75)
    bm25.build_index(DB_PATH)

    # Step 3: Score and rank candidates
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT qid, text FROM queries ORDER BY qid")
    all_queries = c.fetchall()
    print(f"Scoring {len(all_queries)} queries...")

    bm25_run = {}  # qid -> [pid_at_rank1, pid_at_rank2, ...]
    bm25_scores = {}  # qid -> [(pid, score), ...]

    for qid, q_text in all_queries:
        q_tokens = tokenize(q_text)  # Correctly lowercased

        c.execute("SELECT pid FROM candidates WHERE qid = ?", (qid,))
        candidate_pids = [row[0] for row in c.fetchall()]

        scored = []
        for pid in candidate_pids:
            c2 = conn.cursor()
            c2.execute("SELECT text FROM collection WHERE pid = ?", (pid,))
            p_text = c2.fetchone()[0]
            s = bm25.score(q_tokens, p_text, pid)
            scored.append((pid, s))

        scored.sort(key=lambda x: (-x[1], x[0]))
        bm25_run[qid] = [pid for pid, _ in scored]
        bm25_scores[qid] = scored

    conn.close()

    # Step 4: Write MS MARCO format run (1-indexed ranks)
    msmarco_path = os.path.join(OUT_DIR, "bm25_run.tsv")
    with open(msmarco_path, "w") as f:
        for qid in sorted(bm25_run.keys()):
            for rank, pid in enumerate(bm25_run[qid], 1):
                f.write(f"{qid}\t{pid}\t{rank}\n")
    print(f"MS MARCO run: {msmarco_path}")

    # Step 5: Write TREC format run
    trec_path = os.path.join(OUT_DIR, "bm25_run.trec")
    with open(trec_path, "w") as f:
        for qid in sorted(bm25_scores.keys()):
            for rank, (pid, score) in enumerate(bm25_scores[qid], 1):
                f.write(f"{qid} Q0 {pid} {rank} {score:.6f} bm25\n")
    print(f"TREC run: {trec_path}")

    # Step 6: Evaluate all runs
    qrels = load_qrels()

    run_files = {
        "random_run": os.path.join(DATA_DIR, "runs", "random_run.tsv"),
        "tfidf_run": os.path.join(DATA_DIR, "runs", "tfidf_run.tsv"),
        "oracle_run": os.path.join(DATA_DIR, "runs", "oracle_run.tsv"),
    }

    all_metrics = {}

    for name, path in run_files.items():
        run = load_run(path)
        all_metrics[name] = {
            "MRR@10": compute_mrr_at_k(qrels, run, 10),
            "NDCG@10": compute_ndcg_at_k(qrels, run, 10),
            "MAP": compute_map(qrels, run),
            "Recall@10": compute_recall_at_k(qrels, run, 10),
            "Recall@100": compute_recall_at_k(qrels, run, 100),
        }
        print(f"{name}: MRR@10={all_metrics[name]['MRR@10']:.4f}")

    # BM25 run metrics
    all_metrics["bm25_run"] = {
        "MRR@10": compute_mrr_at_k(qrels, bm25_run, 10),
        "NDCG@10": compute_ndcg_at_k(qrels, bm25_run, 10),
        "MAP": compute_map(qrels, bm25_run),
        "Recall@10": compute_recall_at_k(qrels, bm25_run, 10),
        "Recall@100": compute_recall_at_k(qrels, bm25_run, 100),
    }
    print(f"bm25_run: MRR@10={all_metrics['bm25_run']['MRR@10']:.4f}")

    with open(os.path.join(OUT_DIR, "metrics.json"), "w") as f:
        json.dump(all_metrics, f, indent=2)
    print(f"\nMetrics: {OUT_DIR}/metrics.json")

    # Step 7: Cross-validate with official eval script
    print("\nCross-validating with official eval script...")
    result = subprocess.run(
        ["python3", os.path.join(DATA_DIR, "ms_marco_eval.py"),
         QRELS_PATH, msmarco_path],
        capture_output=True, text=True,
    )
    print(result.stdout)


if __name__ == "__main__":
    main()
