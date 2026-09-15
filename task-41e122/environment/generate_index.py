#!/usr/bin/env python3
"""Generate BM25 multi-index data for the forensics and fusion evaluation task."""
import json
import math
import os
import re
from collections import Counter

import bm25s
import numpy as np

corpus = [
    "Information retrieval systems use inverted indices to efficiently search large collections of text documents and enable rapid keyword matching for user queries",
    "Machine learning algorithms learn complex patterns from labeled training data to make accurate predictions on new previously unseen examples and datasets",
    "Relational database management systems store and retrieve structured data efficiently using the structured query language for data manipulation operations",
    "Computer networks enable reliable communication between distributed devices using layered protocols that define rules for data transmission across systems",
    "Operating systems manage hardware resources including processors memory storage and provide essential services for application programs to function correctly",
    "Modern programming languages provide high level abstractions allowing software developers to express algorithms and data structures in readable maintainable code",
    "Comparison based sorting algorithms like quicksort mergesort and heapsort achieve optimal worst case time complexity of order n log n",
    "Graph traversal algorithms including breadth first search and depth first search explore vertices and edges to find paths and connected components",
    "Cryptographic hash functions transform arbitrary length input data into fixed size digest values used for integrity verification and secure password storage",
    "Distributed computing systems coordinate multiple autonomous networked computers that exchange messages and synchronize state to solve large scale problems",
    "Natural language processing applies computational linguistics and machine learning to analyze understand and generate human language text automatically",
    "Computer vision employs convolutional neural networks and image processing to detect classify and segment objects within digital photographs and video frames",
    "Parallel computing architectures divide computational workloads across multiple processor cores to achieve higher throughput and reduced execution time",
    "Software engineering methodologies include agile development test driven design continuous integration and automated deployment for reliable software delivery",
    "Web application frameworks implement model view controller patterns with frontend rendering engines and backend application programming interface service layers",
    "Cloud computing platforms deliver scalable on demand infrastructure services including virtual machines containers object storage and managed database instances",
    "Lossless data compression algorithms exploit statistical patterns and redundancy in source data to reduce storage requirements without information loss",
    "Artificial neural networks consist of interconnected neurons organized in layers that learn representations through backpropagation of gradient error signals",
    "Search engine ranking algorithms evaluate document relevance using term frequency inverse document frequency scores combined with link analysis metrics",
    "Automatic memory management using garbage collection techniques identifies and reclaims unreachable heap allocated objects to prevent memory leaks in programs",
    "Reinforcement learning agents discover optimal behavioral policies through repeated trial and error interaction with stochastic environment dynamics and reward functions",
    "Compiler construction involves multiple phases including lexical scanning syntactic parsing semantic analysis intermediate optimization and target code generation",
    "Formal methods apply mathematical logic and proof techniques to rigorously verify correctness safety and liveness properties of system specifications and implementations",
    "Collaborative filtering recommender systems predict user preferences by identifying similar users or items based on historical interaction and rating patterns",
    "Quantum computation harnesses quantum mechanical superposition entanglement and interference phenomena to exponentially accelerate specific algorithmic computations",
    "Statistical time series models capture temporal dependencies trends and seasonal patterns in sequential observations for forecasting and anomaly detection tasks",
    "Cybersecurity defense mechanisms protect networks and computer systems from unauthorized intrusion data exfiltration denial of service and malware attacks",
    "Blockchain distributed ledger technology records transactions in cryptographically linked blocks validated through decentralized consensus protocols for tamper resistance",
    "Computational biology and bioinformatics analyze genomic sequences protein structures and molecular interaction networks using algorithms and statistical models",
    "Autonomous robotic systems integrate sensor perception motion planning and control algorithms to navigate and manipulate objects in unstructured physical environments",
    "Semantic analysis in natural language understanding resolves lexical ambiguity interprets figurative meaning and extracts structured information from unstructured text",
    "Deep learning architectures with many hidden layers automatically discover hierarchical feature representations from raw pixel audio or text input data",
    "Hard real time systems guarantee deterministic response within strict deadline bounds for mission critical applications in avionics medical devices and industrial control",
    "Geographic information systems integrate spatial databases cartographic visualization and geospatial analysis tools for environmental monitoring and urban infrastructure planning",
    "Distributed version control systems like git track incremental changes to source files enabling parallel development branching merging and complete project history",
    "Pure functional programming paradigms emphasize referential transparency immutable persistent data structures and compositional higher order function abstractions for reliable code",
    "Edge computing architectures process sensor data from internet of things devices locally reducing latency bandwidth consumption and cloud infrastructure dependency",
    "Digital audio processing applies discrete time signal transforms filtering spectral analysis and machine learning for speech recognition and music information retrieval",
    "Real time computer graphics rendering pipelines execute geometric transformation projection rasterization texture mapping and programmable shading operations on graphics hardware",
    "Responsible artificial intelligence frameworks address fairness accountability transparency and societal impact assessment for ethical deployment of automated decision systems",
]

stopwords = [
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for",
    "if", "in", "into", "is", "it", "no", "not", "of", "on", "or",
    "such", "that", "the", "their", "then", "there", "these", "they",
    "this", "to", "was", "will", "with"
]

queries = [
    "information retrieval systems search text documents keyword",
    "machine learning algorithms data training patterns predictions",
    "neural networks architectures layers representations learning",
    "distributed computing systems networks protocols communication",
    "programming languages code generation compilers analysis optimization",
    "cryptographic hash functions security data protection storage",
    "computer vision image processing networks detection objects",
    "algorithms sorting graph search traversal complexity",
    "natural language processing text analysis understanding semantic",
    "cloud computing platforms database services infrastructure storage",
]

os.makedirs("/app/output", exist_ok=True)

with open("/app/corpus.jsonl", "w") as f:
    for i, doc in enumerate(corpus):
        f.write(json.dumps({"id": i, "text": doc}) + "\n")

with open("/app/stopwords.json", "w") as f:
    json.dump(stopwords, f)

with open("/app/queries.json", "w") as f:
    json.dump(queries, f, indent=2)

# --- Build 3 indexes with different BM25 variants ---
configs = {
    "a": {"method": "robertson", "k1": 1.2, "b": 0.55},
    "b": {"method": "atire", "k1": 1.8, "b": 0.80},
    "c": {"method": "lucene", "k1": 1.35, "b": 0.65},
}

misleading = {
    "a": {
        "k1": 1.5, "b": 0.75, "delta": 0.5,
        "method": "lucene", "idf_method": "lucene",
    },
    "b": {
        "k1": 1.2, "b": 0.90, "delta": 0.5,
        "method": "bm25+", "idf_method": "bm25+",
    },
    "c": {
        "k1": 2.0, "b": 0.50, "delta": 0.5,
        "method": "robertson", "idf_method": "robertson",
    },
}

corpus_tokens = bm25s.tokenize(corpus, stopwords=stopwords, stemmer=None)

for name, config in configs.items():
    idx_dir = f"/app/index_{name}"
    os.makedirs(idx_dir, exist_ok=True)
    retriever = bm25s.BM25(**config)
    retriever.index(corpus_tokens)
    retriever.save(idx_dir, corpus=corpus)

    m = misleading[name].copy()
    m["dtype"] = "float32"
    m["int_dtype"] = "int32"
    m["num_docs"] = len(corpus)
    m["version"] = "0.2.12"
    m["backend"] = "numpy"
    with open(f"{idx_dir}/params.index.json", "w") as f:
        json.dump(m, f, indent=4)

# --- Generate graded relevance judgments (qrels) ---
split_fn = re.compile(r"(?u)\b\w\w+\b").findall
stopwords_set = set(stopwords)


def tokenize_text(text):
    return [t for t in split_fn(text.lower()) if t not in stopwords_set]


query_token_lists = [tokenize_text(q) for q in queries]
doc_token_lists = [tokenize_text(d) for d in corpus]

qrels = {}
for qi, qtokens in enumerate(query_token_lists):
    qset = set(qtokens)
    if not qset:
        qrels[str(qi)] = {}
        continue

    doc_scores = []
    for di, dtokens in enumerate(doc_token_lists):
        dcounter = Counter(dtokens)
        overlap = qset.intersection(set(dtokens))
        if not overlap:
            continue
        score = sum(math.log(1 + dcounter[t]) for t in overlap) * len(overlap) / len(qset)
        doc_scores.append((di, score))

    doc_scores.sort(key=lambda x: -x[1])
    relevance = {}
    for rank, (di, _s) in enumerate(doc_scores):
        if rank < 3:
            relevance[str(di)] = 3
        elif rank < 8:
            relevance[str(di)] = 2
        elif rank < 15:
            relevance[str(di)] = 1
    qrels[str(qi)] = relevance

with open("/app/qrels.json", "w") as f:
    json.dump(qrels, f, indent=2)

# Cleanup: remove duplicate corpus files from index dirs
for name in configs:
    for fname in ["corpus.jsonl", "corpus.jsonl.mmindex.npy"]:
        fpath = f"/app/index_{name}/{fname}"
        if os.path.exists(fpath):
            os.remove(fpath)

print(f"Generated 3 indexes: {len(corpus)} docs, {len(queries)} queries")
print(f"Qrels: {sum(len(v) for v in qrels.values())} judgments across {len(queries)} queries")
