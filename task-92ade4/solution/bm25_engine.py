#!/usr/bin/env python3
"""
Standalone BM25 retrieval engine supporting all 5 scoring variants
(robertson, lucene, atire, bm25l, bm25+).

Independent implementation — no external BM25 library dependency.
"""

import json
import math
import re
from collections import Counter
from typing import List, Tuple

import numpy as np


class BM25Engine:
    """BM25 retrieval engine supporting five scoring variants."""

    VALID_METHODS = ("robertson", "lucene", "atire", "bm25l", "bm25+")

    def __init__(
        self,
        method: str = "lucene",
        k1: float = 1.5,
        b: float = 0.75,
        delta: float = 0.5,
    ):
        if method not in self.VALID_METHODS:
            raise ValueError(
                f"Unknown method '{method}'. Choose from {self.VALID_METHODS}"
            )
        self.method = method
        self.k1 = k1
        self.b = b
        self.delta = delta

        # Load stopwords
        with open("/app/stopwords_en.json", "r") as f:
            self.stopwords = set(json.load(f))

        self._splitter = re.compile(r"(?u)\b\w\w+\b")

    # ------------------------------------------------------------------
    # Tokenization
    # ------------------------------------------------------------------

    def _tokenize(self, text: str) -> List[str]:
        text = text.lower()
        tokens = self._splitter.findall(text)
        return [t for t in tokens if t not in self.stopwords]

    # ------------------------------------------------------------------
    # IDF computation (5 variants)
    # ------------------------------------------------------------------

    def _idf(self, df: int, N: int) -> float:
        method = self.method
        if method == "robertson":
            inner = (N - df + 0.5) / (df + 0.5)
            if inner < 1:
                inner = 1.0
            return math.log(inner)
        elif method == "lucene":
            return math.log(1.0 + (N - df + 0.5) / (df + 0.5))
        elif method == "atire":
            return math.log(N / df)
        elif method == "bm25l":
            return math.log((N + 1) / (df + 0.5))
        elif method == "bm25+":
            return math.log((N + 1) / df)
        raise ValueError(method)

    # ------------------------------------------------------------------
    # Term-frequency component (5 variants)
    # ------------------------------------------------------------------

    def _tfc(self, tf, l_d, l_avg) -> float:
        k1, b, delta = self.k1, self.b, self.delta
        method = self.method

        if method in ("robertson", "lucene"):
            return tf / (k1 * ((1 - b) + b * l_d / l_avg) + tf)
        elif method == "atire":
            return (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * l_d / l_avg))
        elif method == "bm25l":
            c = tf / (1 - b + b * l_d / l_avg)
            return ((k1 + 1) * (c + delta)) / (k1 + c + delta)
        elif method == "bm25+":
            num = (k1 + 1) * tf
            den = k1 * (1 - b + b * l_d / l_avg) + tf
            return (num / den) + delta
        raise ValueError(method)

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def index(self, corpus_texts: List[str]):
        """Tokenize raw texts and build a CSC sparse BM25 score matrix."""

        # 1. Tokenize
        corpus_tokens = [self._tokenize(t) for t in corpus_texts]
        self.n_docs = len(corpus_tokens)

        # 2. Build vocabulary (first-appearance order)
        vocab: dict = {}
        for doc_tokens in corpus_tokens:
            for tok in doc_tokens:
                if tok not in vocab:
                    vocab[tok] = len(vocab)
        if "" not in vocab:
            vocab[""] = len(vocab)
        self.vocab = vocab
        n_vocab = len(vocab)

        # 3. Convert to IDs; compute document lengths
        corpus_ids: List[List[int]] = []
        for doc_tokens in corpus_tokens:
            corpus_ids.append([vocab[t] for t in doc_tokens])

        doc_lengths = np.array([len(ids) for ids in corpus_ids])
        avg_doc_len = doc_lengths.mean()  # float64

        # 4. Document frequencies
        doc_freqs: dict = {}
        for doc_ids in corpus_ids:
            for uid in set(doc_ids):
                doc_freqs[uid] = doc_freqs.get(uid, 0) + 1

        # 5. IDF array (float32)
        idf_array = np.zeros(n_vocab, dtype=np.float32)
        for token_id, df in doc_freqs.items():
            idf_array[token_id] = self._idf(df, self.n_docs)

        # 6. Nonoccurrence array (BM25L / BM25+ only)
        uses_nonoccurrence = self.method in ("bm25l", "bm25+")
        if uses_nonoccurrence:
            nonoccurrence = np.zeros(n_vocab, dtype=np.float32)
            for token_id, df in doc_freqs.items():
                idf_val = self._idf(df, self.n_docs)
                tfc_val = self._tfc(0, avg_doc_len, avg_doc_len)
                nonoccurrence[token_id] = idf_val * tfc_val
            self.nonoccurrence = nonoccurrence
        else:
            self.nonoccurrence = None

        # 7. Build score entries (COO-style lists)
        all_scores: list = []
        all_doc_idx: list = []
        all_voc_idx: list = []

        for doc_idx, doc_ids in enumerate(corpus_ids):
            d_len = doc_lengths[doc_idx]
            tf_counts = Counter(doc_ids)

            for token_id, tf in tf_counts.items():
                tfc_val = self._tfc(tf, d_len, avg_doc_len)
                score = idf_array[token_id] * tfc_val

                if uses_nonoccurrence:
                    score -= nonoccurrence[token_id]

                all_scores.append(score)
                all_doc_idx.append(doc_idx)
                all_voc_idx.append(token_id)

        # 8. Convert COO to CSC sparse format
        scores_flat = np.array(all_scores, dtype=np.float32)
        doc_indices = np.array(all_doc_idx, dtype=np.int32)
        voc_indices = np.array(all_voc_idx, dtype=np.int32)

        # indptr from column (vocab) counts
        col_counts = np.bincount(voc_indices, minlength=n_vocab)
        indptr = np.zeros(n_vocab + 1, dtype=np.int64)
        np.cumsum(col_counts, out=indptr[1:])

        # Sort by (column, row) for CSC ordering
        packed = (voc_indices.astype(np.int64) << 32) | doc_indices.astype(np.int64)
        sorter = np.argsort(packed)

        self.csc_data = scores_flat[sorter]
        self.csc_indices = doc_indices[sorter]
        self.csc_indptr = indptr

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self, queries: List[str], k: int = 10
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Return (doc_indices, scores) arrays of shape (n_queries, k)."""

        result_indices: list = []
        result_scores: list = []

        for query_text in queries:
            tokens = self._tokenize(query_text)
            q_ids = [self.vocab[t] for t in tokens if t in self.vocab]

            scores = np.zeros(self.n_docs, dtype=np.float32)

            if len(q_ids) > 0:
                q_ids_arr = np.array(q_ids, dtype=np.int32)

                # Accumulate pre-computed scores from CSC columns
                for tid in q_ids_arr:
                    start = self.csc_indptr[tid]
                    end = self.csc_indptr[tid + 1]
                    np.add.at(
                        scores,
                        self.csc_indices[start:end],
                        self.csc_data[start:end],
                    )

                # Nonoccurrence correction for BM25L / BM25+
                if self.nonoccurrence is not None:
                    scores += self.nonoccurrence[q_ids_arr].sum()

            # Top-k selection
            actual_k = min(k, self.n_docs)
            if actual_k > 0:
                part_idx = np.argpartition(scores, -actual_k)[-actual_k:]
                part_scores = scores[part_idx]
                sort_order = np.flip(np.argsort(part_scores))
                top_idx = part_idx[sort_order]
                top_sc = part_scores[sort_order]
            else:
                top_idx = np.array([], dtype=np.int64)
                top_sc = np.array([], dtype=np.float32)

            result_indices.append(top_idx)
            result_scores.append(top_sc)

        return np.array(result_indices), np.array(result_scores)
