#!/usr/bin/env python3
"""Generate a deterministic corpus and queries for BM25 testing."""

import json
import random
import os

random.seed(42)

# Technical vocabulary for corpus generation
tech_words = [
    "algorithm", "benchmark", "compute", "database", "efficient",
    "framework", "gradient", "heuristic", "inference", "kernel",
    "latency", "matrix", "network", "optimization", "parallel",
    "retrieval", "sparse", "throughput", "vector", "architecture",
    "bandwidth", "cache", "distributed", "embedding", "filter",
    "quantum", "spectral", "polynomial", "recursive", "deterministic",
    "stochastic", "convergence", "eigenvalue", "topology", "manifold",
    "entropy", "variance", "regression", "classification", "clustering",
    "hypothesis", "iteration", "decomposition", "factorization", "interpolation",
    "approximation", "simulation", "calibration", "normalization", "regularization",
]

# Frequency weights
weights = [
    10, 8, 12, 9, 11, 7, 5, 3, 6, 4,
    5, 8, 10, 7, 6, 5, 4, 5, 6, 3,
    3, 7, 4, 3, 5, 2, 2, 3, 3, 2,
    2, 4, 1, 2, 1, 3, 3, 4, 4, 5,
    2, 3, 1, 2, 2, 1, 2, 1, 3, 2,
]

corpus = []
for i in range(500):
    if i < 5:
        length = random.randint(2, 4)
    elif i < 30:
        length = random.randint(4, 10)
    elif i < 400:
        length = random.randint(8, 35)
    else:
        length = random.randint(35, 80)

    doc = random.choices(tech_words, weights=weights, k=length)
    corpus.append({"text": " ".join(doc)})

os.makedirs("/app", exist_ok=True)
with open("/app/corpus.jsonl", "w") as f:
    for doc in corpus:
        f.write(json.dumps(doc) + "\n")

# Test queries spanning common, medium, and rare terms
queries = [
    "algorithm optimization efficient",
    "sparse matrix vector decomposition",
    "network latency throughput bandwidth",
    "quantum topology manifold entropy",
    "distributed parallel compute architecture",
    "eigenvalue convergence stochastic simulation",
    "classification regression clustering variance",
    "cache bandwidth architecture filter",
    "heuristic recursive deterministic polynomial",
    "gradient embedding retrieval inference",
    "spectral entropy normalization regularization",
    "framework kernel compute database",
    "benchmark throughput latency optimization",
    "filter sparse vector factorization",
    "approximation interpolation calibration",
]
with open("/app/queries.json", "w") as f:
    json.dump(queries, f, indent=2)

# English stopwords
stopwords = [
    "a", "an", "and", "are", "as", "at", "be", "but", "by",
    "for", "if", "in", "into", "is", "it", "no", "not", "of",
    "on", "or", "such", "that", "the", "their", "then", "there",
    "these", "they", "this", "to", "was", "will", "with",
]
with open("/app/stopwords_en.json", "w") as f:
    json.dump(stopwords, f, indent=2)

print(f"Generated corpus with {len(corpus)} documents")
print(f"Generated {len(queries)} queries")
print(f"Stopwords list: {len(stopwords)} words")
