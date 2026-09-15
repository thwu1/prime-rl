#!/usr/bin/env python3
"""Baseline BM25 retriever for BRIGHT Pony dataset.

This is a minimal keyword-matching baseline. On reasoning-intensive queries
it achieves approximately nDCG@10 of 0.04-0.06 because relevant documents
often use entirely different vocabulary than the query.

Run:  python3 /app/baseline/bm25_baseline.py
"""
import json
import math
import re
from collections import Counter


def tokenize(text):
    """Basic whitespace/punctuation tokenizer."""
    return [t for t in re.findall(r'[a-z0-9]+', text.lower()) if len(t) > 1]


class SimpleBM25:
    def __init__(self, k1=1.2, b=0.75):
        self.k1 = k1
        self.b = b

    def fit(self, docs_tokenized):
        self.N = len(docs_tokenized)
        self.doc_lens = []
        self.doc_tfs = []
        self.df = Counter()
        for tokens in docs_tokenized:
            self.doc_lens.append(len(tokens))
            tf = Counter(tokens)
            self.doc_tfs.append(tf)
            for term in tf:
                self.df[term] += 1
        self.avgdl = sum(self.doc_lens) / max(self.N, 1)

    def score_query(self, query_tokens):
        scores = [0.0] * self.N
        for term in set(query_tokens):
            if term not in self.df:
                continue
            df = self.df[term]
            idf = math.log((self.N - df + 0.5) / (df + 0.5) + 1.0)
            for i, tf_dict in enumerate(self.doc_tfs):
                if term in tf_dict:
                    tf = tf_dict[term]
                    dl = self.doc_lens[i]
                    num = tf * (self.k1 + 1)
                    den = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                    scores[i] += idf * num / den
        return scores


def main():
    with open('/app/data/examples.json') as f:
        examples = json.load(f)
    with open('/app/data/documents.json') as f:
        documents = json.load(f)

    doc_ids = [str(d['id']) for d in documents]
    doc_contents = [d['content'] for d in documents]

    print(f"Building BM25 index over {len(documents)} documents...")
    tokenized_docs = [tokenize(c) for c in doc_contents]
    bm25 = SimpleBM25()
    bm25.fit(tokenized_docs)

    all_scores = {}
    for ex in examples:
        qid = str(ex['id'])
        excluded = set(str(x) for x in ex.get('excluded_ids', []))

        query_tokens = tokenize(ex['query'])
        raw_scores = bm25.score_query(query_tokens)

        doc_scores = {}
        for did, s in zip(doc_ids, raw_scores):
            if did not in excluded and s > 0:
                doc_scores[did] = round(s, 6)

        sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)[:1000]
        all_scores[qid] = dict(sorted_docs)

    import os
    os.makedirs('/app/baseline/output', exist_ok=True)
    with open('/app/baseline/output/scores.json', 'w') as f:
        json.dump(all_scores, f)

    avg_docs = sum(len(v) for v in all_scores.values()) / max(len(all_scores), 1)
    print(f"Scored {len(all_scores)} queries, avg {avg_docs:.0f} docs/query")
    print("Baseline scores saved to /app/baseline/output/scores.json")
    print()
    print("NOTE: This baseline uses simple BM25 with basic tokenization.")
    print("Reasoning-intensive queries require approaches beyond keyword matching.")


if __name__ == '__main__':
    main()
