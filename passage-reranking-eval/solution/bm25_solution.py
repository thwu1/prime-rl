#!/usr/bin/env python3
"""
BM25 reranker and multi-metric IR evaluation pipeline.

Reads MS MARCO-format data from /app/data/, produces:
  /app/output/bm25_run.tsv   - BM25 reranking in qid\tpid\trank format
  /app/output/metrics.json    - MRR@10, NDCG@10, MAP, Recall@10, Recall@100
"""


import math
import json
import os
from collections import Counter, defaultdict

# ── Data loading ─────────────────────────────────────────────────────────────

def load_collection(path):
    """Load collection.tsv -> {pid: text}"""
    coll = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t', 1)
            coll[int(parts[0])] = parts[1]
    return coll

def load_queries(path):
    """Load queries.tsv -> {qid: text}"""
    qs = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t', 1)
            qs[int(parts[0])] = parts[1]
    return qs

def load_qrels(path):
    """Load TREC qrels -> {qid: set(pids)}"""
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            qid = int(parts[0])
            pid = int(parts[2])
            if qid not in qrels:
                qrels[qid] = set()
            qrels[qid].add(pid)
    return qrels

def load_candidates(path):
    """Load top100.tsv -> {qid: [(pid, passage_text), ...]}"""
    cands = defaultdict(list)
    seen = defaultdict(set)
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t', 3)
            qid = int(parts[0])
            pid = int(parts[1])
            if pid not in seen[qid]:
                seen[qid].add(pid)
                cands[qid].append((pid, parts[3]))
    return dict(cands)

def load_run(path):
    """Load run file -> {qid: [pid_at_rank1, pid_at_rank2, ...]}"""
    raw = defaultdict(dict)
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            qid = int(parts[0])
            pid = int(parts[1])
            rank = int(parts[2])
            raw[qid][rank] = pid
    result = {}
    for qid, rank_map in raw.items():
        max_r = max(rank_map.keys())
        result[qid] = [rank_map.get(r, 0) for r in range(1, max_r + 1)]
    return result

# ── Tokenizer ────────────────────────────────────────────────────────────────

def tokenize(text):
    return text.lower().split()

# ── BM25 Implementation ─────────────────────────────────────────────────────

class BM25:
    def __init__(self, collection, k1=1.2, b=0.75):
        self.k1 = k1
        self.b = b
        self.N = len(collection)
        self.doc_lens = {}
        self.df = Counter()

        total_len = 0
        for pid, text in collection.items():
            tokens = tokenize(text)
            self.doc_lens[pid] = len(tokens)
            total_len += len(tokens)
            for term in set(tokens):
                self.df[term] += 1

        self.avg_dl = total_len / self.N if self.N > 0 else 1.0

    def idf(self, term):
        n = self.df.get(term, 0)
        return math.log((self.N - n + 0.5) / (n + 0.5) + 1.0)

    def score(self, query_text, passage_text, pid):
        q_tokens = tokenize(query_text)
        p_tokens = tokenize(passage_text)
        dl = self.doc_lens.get(pid, len(p_tokens))
        tf_map = Counter(p_tokens)

        s = 0.0
        for qt in q_tokens:
            if qt not in tf_map:
                continue
            tf = tf_map[qt]
            idf_val = self.idf(qt)
            tf_norm = (tf * (self.k1 + 1)) / (
                tf + self.k1 * (1 - self.b + self.b * dl / self.avg_dl)
            )
            s += idf_val * tf_norm
        return s

# ── Metrics ──────────────────────────────────────────────────────────────────

def compute_mrr_at_k(qrels, run, k=10):
    """Mean Reciprocal Rank @ k."""
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
    """Normalized Discounted Cumulative Gain @ k (binary relevance)."""
    ndcg_sum = 0.0
    for qid, rel_pids in qrels.items():
        if qid not in run:
            continue
        ranked = run[qid]

        # DCG@k
        dcg = 0.0
        for i in range(min(k, len(ranked))):
            if ranked[i] in rel_pids:
                dcg += 1.0 / math.log2(i + 2)

        # IDCG@k
        n_rel = len(rel_pids)
        idcg = sum(1.0 / math.log2(j + 2) for j in range(min(n_rel, k)))

        if idcg > 0:
            ndcg_sum += dcg / idcg

    return ndcg_sum / len(qrels)

def compute_map(qrels, run, max_rank=None):
    """Mean Average Precision."""
    ap_sum = 0.0
    for qid, rel_pids in qrels.items():
        if qid not in run:
            continue
        ranked = run[qid]
        limit = min(max_rank, len(ranked)) if max_rank else len(ranked)
        n_rel_found = 0
        ap = 0.0
        for i in range(limit):
            if ranked[i] in rel_pids:
                n_rel_found += 1
                ap += n_rel_found / (i + 1)
        total_rel = len(rel_pids)
        if total_rel > 0:
            ap_sum += ap / total_rel

    return ap_sum / len(qrels)

def compute_recall_at_k(qrels, run, k):
    """Recall @ k."""
    recall_sum = 0.0
    for qid, rel_pids in qrels.items():
        if qid not in run:
            continue
        ranked = run[qid]
        retrieved = set(ranked[:min(k, len(ranked))])
        recall_sum += len(retrieved & rel_pids) / len(rel_pids)

    return recall_sum / len(qrels)

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    data_dir = "/app/data"
    out_dir = "/app/output"
    os.makedirs(out_dir, exist_ok=True)

    print("Loading data...")
    collection = load_collection(os.path.join(data_dir, "collection.tsv"))
    queries = load_queries(os.path.join(data_dir, "queries.tsv"))
    qrels = load_qrels(os.path.join(data_dir, "qrels.tsv"))
    cands = load_candidates(os.path.join(data_dir, "top100.tsv"))

    # ── BM25 reranking ───────────────────────────────────────────────────
    print("Building BM25 index over collection...")
    bm25 = BM25(collection, k1=1.2, b=0.75)

    print("Scoring candidates...")
    bm25_run_path = os.path.join(out_dir, "bm25_run.tsv")
    bm25_run = {}
    with open(bm25_run_path, "w") as f:
        for qid in sorted(cands.keys()):
            q_text = queries[qid]
            scored = []
            for pid, p_text in cands[qid]:
                s = bm25.score(q_text, p_text, pid)
                scored.append((pid, s))
            scored.sort(key=lambda x: (-x[1], x[0]))
            ranked_list = []
            for rank, (pid, _) in enumerate(scored, 1):
                f.write(f"{qid}\t{pid}\t{rank}\n")
                ranked_list.append(pid)
            bm25_run[qid] = ranked_list

    # ── Evaluate all runs ────────────────────────────────────────────────
    run_files = {
        "random_run": os.path.join(data_dir, "baseline_runs", "random_run.tsv"),
        "tfidf_run": os.path.join(data_dir, "baseline_runs", "tfidf_run.tsv"),
        "oracle_run": os.path.join(data_dir, "baseline_runs", "oracle_run.tsv"),
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

    # BM25 run
    all_metrics["bm25_run"] = {
        "MRR@10": compute_mrr_at_k(qrels, bm25_run, 10),
        "NDCG@10": compute_ndcg_at_k(qrels, bm25_run, 10),
        "MAP": compute_map(qrels, bm25_run),
        "Recall@10": compute_recall_at_k(qrels, bm25_run, 10),
        "Recall@100": compute_recall_at_k(qrels, bm25_run, 100),
    }
    print(f"bm25_run: MRR@10={all_metrics['bm25_run']['MRR@10']:.4f}")

    with open(os.path.join(out_dir, "metrics.json"), "w") as f:
        json.dump(all_metrics, f, indent=2)

    print(f"\nResults written to {out_dir}/metrics.json")

if __name__ == "__main__":
    main()
