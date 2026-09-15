#!/usr/bin/env python3

"""Multi-signal retrieval for BRIGHT Pony: sentence-transformers + BM25 + TF-IDF with RRF.

This solution builds a hybrid retrieval pipeline without using any relevance
labels. It combines four complementary signals via Reciprocal Rank Fusion to
handle the reasoning-intensive nature of the queries.
"""

import json
import math
import os
import re
import numpy as np
from collections import Counter, defaultdict


STOP_WORDS = frozenset([
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'can', 'shall', 'to', 'of', 'in', 'for',
    'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during',
    'before', 'after', 'this', 'that', 'these', 'those', 'it', 'its',
    'i', 'me', 'my', 'we', 'our', 'you', 'your', 'he', 'him', 'his',
    'she', 'her', 'they', 'them', 'their', 'what', 'which', 'who',
    'where', 'when', 'why', 'how', 'all', 'each', 'every', 'both',
    'few', 'more', 'most', 'other', 'some', 'such', 'no', 'not',
    'only', 'same', 'so', 'than', 'too', 'very', 'and', 'but', 'or',
    'if', 'then', 'else', 'about', 'just', 'also', 'am', 'there',
    'here', 'out', 'up', 'down', 'off', 'over', 'under', 'again',
    'further', 'once', 'own', 'nor',
])


def preprocess(text):
    """Split camelCase/snake_case identifiers, lowercase, tokenize, filter."""
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = text.replace('_', ' ').lower()
    tokens = re.findall(r'[a-z0-9]+', text)
    return [t for t in tokens if t not in STOP_WORDS and len(t) > 1]


class BM25:
    """BM25 with Lucene-style non-negative IDF."""

    def __init__(self, k1=0.9, b=0.4):
        self.k1 = k1
        self.b = b

    def fit(self, tokenized_docs):
        self.N = len(tokenized_docs)
        self.doc_len = []
        self.doc_terms = []
        self.doc_freqs = Counter()
        for doc in tokenized_docs:
            self.doc_len.append(len(doc))
            tf = Counter(doc)
            self.doc_terms.append(tf)
            for term in tf:
                self.doc_freqs[term] += 1
        self.avgdl = sum(self.doc_len) / max(self.N, 1)

    def score(self, query_tokens):
        scores = np.zeros(self.N)
        for term in set(query_tokens):
            if term not in self.doc_freqs:
                continue
            df = self.doc_freqs[term]
            idf = math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))
            for i, doc_tf in enumerate(self.doc_terms):
                if term in doc_tf:
                    tf = doc_tf[term]
                    dl = self.doc_len[i]
                    num = tf * (self.k1 + 1)
                    den = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                    scores[i] += idf * num / den
        return scores


def reciprocal_rank_fusion(rankings, k=60):
    """Combine multiple ranked lists via RRF."""
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, (doc_id, _) in enumerate(ranking):
            scores[doc_id] += 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def main():
    from sentence_transformers import SentenceTransformer
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    # Load data
    with open('/app/data/examples.json') as f:
        examples = json.load(f)
    with open('/app/data/documents.json') as f:
        documents = json.load(f)

    print(f"Loaded {len(examples)} queries and {len(documents)} documents")

    doc_ids = [str(d['id']) for d in documents]
    doc_contents = [d['content'] for d in documents]
    queries = [ex['query'] for ex in examples]

    # === Signal 1: Dense sentence embeddings ===
    print("Loading sentence-transformers model...")
    st_model = SentenceTransformer('all-mpnet-base-v2')

    print("Encoding documents...")
    doc_embs = st_model.encode(doc_contents, show_progress_bar=True,
                               batch_size=64, normalize_embeddings=True)
    print("Encoding queries...")
    query_embs = st_model.encode(queries, show_progress_bar=True,
                                 batch_size=64, normalize_embeddings=True)
    st_sim = cosine_similarity(query_embs, doc_embs)

    # === Signal 2: BM25 with code-aware preprocessing ===
    print("Building BM25 index...")
    preprocessed_docs = [preprocess(c) for c in doc_contents]
    bm25 = BM25(k1=0.9, b=0.4)
    bm25.fit(preprocessed_docs)

    # === Signal 3: TF-IDF with word n-grams ===
    print("Building TF-IDF index...")
    processed_texts = [
        re.sub(r'([a-z])([A-Z])', r'\1 \2', c).replace('_', ' ').lower()
        for c in doc_contents
    ]
    tfidf = TfidfVectorizer(
        max_features=100000,
        sublinear_tf=True,
        token_pattern=r'[a-z0-9]+',
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.95,
    )
    tfidf_matrix = tfidf.fit_transform(processed_texts)

    # === Combine per query via RRF ===
    print("Scoring queries...")
    all_scores = {}

    for i, ex in enumerate(examples):
        qid = str(ex['id'])
        query = ex['query']
        excluded = set(str(x) for x in ex.get('excluded_ids', []))

        # BM25 scores
        q_tokens = preprocess(query)
        bm25_scores = bm25.score(q_tokens)

        # BM25 with pseudo-relevance feedback (query expansion)
        top5_idx = np.argsort(bm25_scores)[::-1][:5]
        expansion = Counter()
        for idx in top5_idx:
            for term in preprocessed_docs[idx]:
                expansion[term] += 1
        q_set = set(q_tokens)
        expanded = q_tokens + [t for t, _ in expansion.most_common(25)
                               if t not in q_set]
        bm25_prf = bm25.score(expanded)

        # Sentence-transformer scores
        st_scores = st_sim[i]

        # TF-IDF scores
        q_processed = re.sub(r'([a-z])([A-Z])', r'\1 \2', query).replace('_', ' ').lower()
        q_vec = tfidf.transform([q_processed])
        tfidf_scores = cosine_similarity(q_vec, tfidf_matrix).flatten()

        # Build rankings for RRF (4 signals: ST, BM25+PRF, TF-IDF, raw BM25)
        rankings = []
        for signal in [st_scores, bm25_prf, tfidf_scores, bm25_scores]:
            ranking = [(did, float(s)) for did, s in zip(doc_ids, signal)
                       if did not in excluded]
            ranking.sort(key=lambda x: x[1], reverse=True)
            rankings.append(ranking[:500])

        combined = reciprocal_rank_fusion(rankings)[:1000]
        all_scores[qid] = {did: float(score) for did, score in combined}

        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(examples)} queries")

    print(f"Retrieval complete for {len(all_scores)} queries")

    # Save scores only — no ground truth available for metric computation
    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/scores.json', 'w') as f:
        json.dump(all_scores, f)
    print("Scores written to /app/results/scores.json")


if __name__ == '__main__':
    main()
