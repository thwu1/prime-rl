#!/usr/bin/env python3
"""
Draft IR evaluation script.
Status: produces partial results, needs review and completion.
"""
import json
import math
import os
import re
from collections import Counter, defaultdict

DATA_DIR = "/app/data"
OUTPUT_PATH = "/app/results.json"


def tokenize(text):
    """Simple whitespace tokenizer."""
    return text.lower().split()


class BM25:
    def __init__(self, corpus, k1=1.2, b=0.75):
        self.k1 = k1
        self.b = b
        self.N = len(corpus)
        self.doc_ids = [doc["docid"] for doc in corpus]
        self.doc_tokens = [tokenize(doc["text"]) for doc in corpus]
        self.doc_lens = [len(t) for t in self.doc_tokens]
        self.avgdl = sum(self.doc_lens) / len(self.doc_lens)
        self.df = Counter()
        self.tf = []
        for tokens in self.doc_tokens:
            tf = Counter(tokens)
            self.tf.append(tf)
            for term in set(tokens):
                self.df[term] += 1

    def _idf(self, term):
        df = self.df.get(term, 0)
        return math.log(self.N / (df + 1))

    def retrieve(self, query_text, top_k=100):
        tokens = tokenize(query_text)
        scores = []
        for i in range(self.N):
            s = 0.0
            for term in tokens:
                tf = self.tf[i].get(term, 0)
                if tf > 0:
                    idf = self._idf(term)
                    s += idf * (1 + math.log(1 + tf))
            scores.append((self.doc_ids[i], s))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]


def compute_ndcg(qrels, run, k):
    per_query = {}
    for qid in run:
        if qid not in qrels:
            continue
        ranking = [docid for docid, _ in run[qid][:k]]
        gains = [qrels[qid].get(d, 0) for d in ranking]
        dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
        ideal_gains = sorted(qrels[qid].values(), reverse=True)[:k]
        idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal_gains))
        per_query[qid] = dcg / idcg if idcg > 0 else 0.0
    avg = sum(per_query.values()) / len(per_query) if per_query else 0.0
    return avg, per_query


def compute_map(qrels, run, k):
    per_query = {}
    for qid in run:
        if qid not in qrels:
            continue
        relevant = {d for d, r in qrels[qid].items() if r >= 1}
        ranking = [docid for docid, _ in run[qid][:k]]
        num_rel = 0
        sum_prec = 0.0
        for i, docid in enumerate(ranking):
            if docid in relevant:
                num_rel += 1
                sum_prec += num_rel / (i + 1)
        per_query[qid] = sum_prec / len(relevant) if relevant else 0.0
    avg = sum(per_query.values()) / len(per_query) if per_query else 0.0
    return avg, per_query


def load_qrels(task_dir):
    qrels = {}
    with open(os.path.join(task_dir, "qrels.tsv")) as f:
        for line in f:
            parts = line.strip().split("\t")
            qid, _, docid, rel = parts
            qrels.setdefault(qid, {})[docid] = int(rel)
    return qrels


def load_run(path):
    run = defaultdict(list)
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t")
            qid, _, docid, rank, score, _ = parts
            run[qid].append((docid, float(score)))
    for qid in run:
        run[qid].sort(key=lambda x: -x[1])
    return dict(run)


def load_corpus(task_dir):
    corpus = []
    with open(os.path.join(task_dir, "corpus.jsonl")) as f:
        for line in f:
            corpus.append(json.loads(line))
    return corpus


def load_queries(task_dir):
    queries = []
    with open(os.path.join(task_dir, "queries.jsonl")) as f:
        for line in f:
            queries.append(json.loads(line))
    return queries


def main():
    tasks = sorted(d for d in os.listdir(DATA_DIR)
                   if os.path.isdir(os.path.join(DATA_DIR, d)))

    per_task = {}
    for task_name in tasks:
        task_dir = os.path.join(DATA_DIR, task_name)
        qrels = load_qrels(task_dir)
        corpus = load_corpus(task_dir)
        queries = load_queries(task_dir)

        task_results = {}

        # Evaluate neural runs
        for sys_name in ["neural_a", "neural_b"]:
            run = load_run(os.path.join(task_dir, "runs", f"{sys_name}.tsv"))
            ndcg5, _ = compute_ndcg(qrels, run, 5)
            ndcg10, _ = compute_ndcg(qrels, run, 10)
            map10, _ = compute_map(qrels, run, 10)
            task_results[sys_name] = {
                "ndcg@5": round(ndcg5, 6),
                "ndcg@10": round(ndcg10, 6),
                "map@10": round(map10, 6),
            }

        # BM25 plain mode
        bm25 = BM25(corpus)
        bm25_run = {}
        for q in queries:
            bm25_run[q["qid"]] = bm25.retrieve(q["text"])

        ndcg5, _ = compute_ndcg(qrels, bm25_run, 5)
        ndcg10, _ = compute_ndcg(qrels, bm25_run, 10)
        map10, _ = compute_map(qrels, bm25_run, 10)
        task_results["bm25_plain"] = {
            "ndcg@5": round(ndcg5, 6),
            "ndcg@10": round(ndcg10, 6),
            "map@10": round(map10, 6),
        }

        per_task[task_name] = task_results

    output = {"per_task": per_task}
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Results written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
