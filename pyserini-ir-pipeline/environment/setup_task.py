#!/usr/bin/env python3
"""Set up the IR diagnosis task: corpus, inverted index, queries, qrels, baselines, targets."""

import json
import os
import sys

sys.path.insert(0, '/app/tools')
from bm25_search import tokenize, search_bm25, search_qld, write_run
from evaluate import load_qrels, load_run, compute_metrics

os.makedirs('/app/corpus', exist_ok=True)
os.makedirs('/app/runs', exist_ok=True)

# ---- Documents ----
documents = [
    {"id": "doc001", "contents": "Information retrieval is the science of searching for information in documents, searching for documents themselves, and searching for metadata about documents. Modern information retrieval systems use sophisticated ranking models to order results by relevance to user queries."},
    {"id": "doc002", "contents": "The BM25 ranking function is a probabilistic model used in information retrieval to estimate the relevance of documents to a given search query. It considers term frequency, inverse document frequency, and document length normalization through parameters k1 and b."},
    {"id": "doc003", "contents": "Query expansion techniques improve retrieval effectiveness by adding related terms to the original query. Pseudo-relevance feedback methods like RM3 assume that top-ranked documents from an initial retrieval are relevant and extract expansion terms from them to reformulate the query."},
    {"id": "doc004", "contents": "Inverted indexes are the fundamental data structure underlying modern search engines. An inverted index maps terms to the list of documents containing them, along with term frequencies and positional information for phrase queries and proximity scoring."},
    {"id": "doc005", "contents": "Evaluation metrics for information retrieval include mean average precision, normalized discounted cumulative gain, and recall at various cutoff points. These metrics measure different aspects of ranking quality and are computed using human relevance judgments called qrels."},
    {"id": "doc006", "contents": "The vector space model represents documents and queries as vectors in a high-dimensional term space. Cosine similarity between document and query vectors provides a relevance score for ranking. TF-IDF weighting is commonly used for computing vector components."},
    {"id": "doc007", "contents": "Lucene is an open-source search engine library written in Java that provides full-text indexing and searching capabilities. It implements efficient inverted index construction and supports various similarity models including BM25, language models, and divergence from randomness."},
    {"id": "doc008", "contents": "Relevance feedback allows users to mark retrieved documents as relevant or non-relevant, enabling the system to refine subsequent searches. The Rocchio algorithm modifies the query vector by moving it toward relevant document vectors and away from non-relevant ones."},
    {"id": "doc009", "contents": "Language models for information retrieval estimate the probability of generating a query from a document-specific language model. Smoothing techniques such as Dirichlet prior smoothing and Jelinek-Mercer smoothing prevent zero probabilities for unseen query terms."},
    {"id": "doc010", "contents": "Reciprocal rank fusion combines results from multiple retrieval systems by computing a weighted sum of reciprocal ranks across different result lists. This unsupervised fusion method is robust and does not require training data or parameter tuning beyond the constant k."},
    {"id": "doc011", "contents": "Deep neural networks with multiple hidden layers learn hierarchical feature representations from raw data. Convolutional neural networks excel at image recognition tasks while recurrent neural networks handle sequential data processing in natural language understanding."},
    {"id": "doc012", "contents": "Gradient descent optimization algorithms minimize loss functions by iteratively adjusting model parameters in the direction of steepest descent. Stochastic gradient descent processes mini-batches of training data for improved computational efficiency and implicit regularization."},
    {"id": "doc013", "contents": "Transfer learning enables models pre-trained on large datasets to be fine-tuned for specific downstream tasks with limited labeled data. BERT and other transformer-based models have revolutionized natural language processing through masked language model pre-training objectives."},
    {"id": "doc014", "contents": "Support vector machines find optimal hyperplanes that maximize the margin between classes in the feature space. The kernel trick allows SVMs to operate implicitly in high-dimensional spaces without computing explicit feature map transformations."},
    {"id": "doc015", "contents": "Random forests combine multiple decision trees trained on bootstrap samples of the training data. Bagging reduces overfitting by averaging predictions across diverse base learners while maintaining low bias and reducing overall prediction variance."},
    {"id": "doc016", "contents": "Reinforcement learning agents interact with environments to maximize cumulative rewards through trial and error exploration. Q-learning and policy gradient methods represent fundamental algorithmic approaches for learning optimal decision-making strategies."},
    {"id": "doc017", "contents": "Generative adversarial networks consist of a generator network and a discriminator network trained in a minimax game framework. The generator creates synthetic data samples while the discriminator learns to distinguish real data from generated samples."},
    {"id": "doc018", "contents": "Neural information retrieval models use deep learning to compute relevance scores between queries and documents. Cross-encoder architectures jointly encode query-document pairs for precise scoring while bi-encoder architectures independently encode queries and documents into dense vector representations for efficient large-scale retrieval."},
    {"id": "doc019", "contents": "Attention mechanisms allow neural networks to selectively focus on relevant parts of the input when producing each output element. The transformer architecture relies entirely on multi-head self-attention and has become the dominant paradigm for sequence modeling tasks."},
    {"id": "doc020", "contents": "Regularization techniques prevent neural network overfitting by adding constraints or noise during the training process. Dropout randomly zeros out neuron activations at each training step while weight decay adds L2 penalty terms to the loss function."},
    {"id": "doc021", "contents": "Relational database management systems organize data in tables with rows and columns following Edgar Codd's relational model. SQL provides a declarative query language for data definition, manipulation, and retrieval from relational databases."},
    {"id": "doc022", "contents": "Query optimization in database systems transforms declarative SQL queries into efficient physical execution plans. Cost-based optimizers estimate the computational cost of alternative query plans using statistics about data distribution, cardinality estimates, and available indexes."},
    {"id": "doc023", "contents": "B-tree indexes accelerate database lookups by organizing keys in a balanced tree structure with high fan-out. Secondary indexes on frequently queried columns dramatically reduce the number of disk page accesses required to answer range and equality queries."},
    {"id": "doc024", "contents": "Transaction processing ensures the ACID properties of atomicity, consistency, isolation, and durability in concurrent database operations. Two-phase locking and multiversion concurrency control are widely deployed protocols for managing concurrent transactions."},
    {"id": "doc025", "contents": "Distributed database systems partition data across multiple nodes to achieve horizontal scalability and fault tolerance. Consistent hashing determines data placement across the cluster while replication strategies ensure availability when individual nodes fail."},
    {"id": "doc026", "contents": "NoSQL databases sacrifice some relational guarantees for improved horizontal scalability and schema flexibility. Document stores, key-value stores, column-family stores, and graph databases each optimize for different data access patterns and workload characteristics."},
    {"id": "doc027", "contents": "Database query processing involves parsing, optimization, and execution phases to transform user queries into results. Join algorithms including nested loop join, hash join, and sort-merge join have different performance characteristics depending on data size, available memory, and index availability."},
    {"id": "doc028", "contents": "Data warehousing systems optimize for analytical queries over large historical datasets using denormalized schemas. Star and snowflake schemas organize fact tables and dimension tables for efficient OLAP queries and multidimensional data analysis."},
    {"id": "doc029", "contents": "Stream processing engines handle continuous queries over unbounded data streams in near real time. Systems like Apache Flink provide exactly-once processing semantics and windowing operations for aggregating and analyzing streaming event data."},
    {"id": "doc030", "contents": "Database indexing strategies must balance read performance improvements against write overhead costs. Write-optimized structures like log-structured merge trees batch updates in memory before flushing sorted runs to disk, achieving high write throughput at the cost of read amplification."},
    {"id": "doc031", "contents": "Virtual memory systems use page tables to translate virtual addresses to physical addresses, giving each process the illusion of a large private address space. Page faults occur when accessed pages are not resident in physical memory and must be loaded from secondary storage."},
    {"id": "doc032", "contents": "Page replacement algorithms determine which memory pages to evict when physical memory is exhausted. The optimal algorithm replaces the page that will not be used for the longest future period, but practical algorithms like LRU and Clock approximate this theoretical ideal."},
    {"id": "doc033", "contents": "Process scheduling algorithms allocate CPU time slices to competing processes and threads. Priority-based scheduling, round-robin scheduling, and completely fair scheduling each offer different tradeoffs between throughput, latency, and fairness guarantees."},
    {"id": "doc034", "contents": "File systems organize persistent data on storage devices into hierarchical directory structures with metadata. Modern file systems like ext4, XFS, and ZFS use journaling or copy-on-write techniques to maintain data consistency after unexpected system crashes."},
    {"id": "doc035", "contents": "Inter-process communication mechanisms enable processes to exchange data and synchronize their execution. Pipes, message queues, shared memory segments, and network sockets provide different abstractions for communication between cooperating processes."},
    {"id": "doc036", "contents": "Memory management in operating systems involves allocating and deallocating physical memory pages to processes on demand. The kernel maintains free page lists and uses buddy allocation or slab allocation algorithms to efficiently manage memory regions of varying sizes."},
    {"id": "doc037", "contents": "Deadlock occurs when processes hold resources while waiting for resources held by other processes in a circular dependency chain. Deadlock prevention, avoidance using Banker's algorithm, detection through wait-for graphs, and recovery strategies address this fundamental concurrency problem."},
    {"id": "doc038", "contents": "Container virtualization uses Linux kernel namespaces and control groups to isolate processes without the overhead of full hardware virtualization. Docker containers share the host operating system kernel while providing resource isolation and portable application packaging."},
    {"id": "doc039", "contents": "The translation lookaside buffer caches recently used page table entries to accelerate virtual-to-physical address translation. TLB misses trigger hardware or software page table walks that may traverse multiple levels of page tables in modern 64-bit architectures."},
    {"id": "doc040", "contents": "Kernel synchronization primitives including spinlocks, mutexes, semaphores, and read-write locks protect shared kernel data structures from concurrent access by multiple processors. Lock-free and wait-free algorithms eliminate blocking but require careful use of atomic compare-and-swap operations."},
    {"id": "doc041", "contents": "Public key cryptography enables secure communication without requiring pre-shared secret keys between parties. RSA encryption relies on the computational difficulty of factoring large semiprime numbers, while elliptic curve cryptography achieves equivalent security strength with significantly shorter key lengths."},
    {"id": "doc042", "contents": "Symmetric encryption algorithms like AES use a single shared secret key for both encryption and decryption operations. Block cipher modes of operation including CBC, CTR, and GCM determine how individual plaintext blocks are processed and how ciphertext integrity is verified."},
    {"id": "doc043", "contents": "Cryptographic hash functions map arbitrary-length inputs to fixed-length message digests with collision resistance, preimage resistance, and second preimage resistance properties. SHA-256 and SHA-3 are widely deployed for data integrity verification, digital signatures, and password hashing."},
    {"id": "doc044", "contents": "Digital signature schemes combine asymmetric cryptography with cryptographic hash functions to provide message authentication, integrity verification, and non-repudiation guarantees. The signer hashes the message and encrypts the digest with their private key, producing a signature verifiable with the corresponding public key."},
    {"id": "doc045", "contents": "Key exchange protocols enable two communicating parties to establish a shared secret key over an insecure communication channel. Diffie-Hellman key exchange relies on the discrete logarithm problem, while post-quantum key exchange algorithms use lattice-based or code-based hardness assumptions."},
    {"id": "doc046", "contents": "Transport layer security protects network communications through authenticated encryption between endpoints. The TLS handshake protocol negotiates cipher suites, performs key exchange, authenticates server certificates, and establishes encrypted channels for confidential data transmission."},
    {"id": "doc047", "contents": "Access control systems enforce authorization policies determining which subjects can perform which operations on protected objects. Role-based access control and attribute-based access control are common models for managing fine-grained permissions in enterprise information systems."},
    {"id": "doc048", "contents": "Side-channel attacks exploit implementation artifacts such as timing variations, power consumption patterns, or electromagnetic emissions to extract secret cryptographic keys from hardware implementations. Constant-time programming practices and masking countermeasures help mitigate these physical attack vectors."},
    {"id": "doc049", "contents": "Homomorphic encryption allows computations to be performed directly on encrypted data without requiring decryption. Fully homomorphic encryption schemes support arbitrary computations on ciphertexts but incur orders of magnitude performance overhead compared to plaintext computation."},
    {"id": "doc050", "contents": "Zero-knowledge proofs enable a prover to convince a verifier of a mathematical statement's truth without revealing any information beyond the statement's validity. ZK-SNARKs and ZK-STARKs provide succinct non-interactive proof systems used in blockchain privacy and verifiable computation protocols."},
]

with open('/app/corpus/docs.jsonl', 'w') as f:
    for doc in documents:
        f.write(json.dumps(doc) + '\n')

# ---- Build inverted index ----
postings = {}
doc_lengths = {}
collection_freqs = {}
total_terms = 0

for doc in documents:
    docid = doc['id']
    tokens = tokenize(doc['contents'])
    doc_lengths[docid] = len(tokens)
    total_terms += len(tokens)
    term_counts = {}
    for token in tokens:
        term_counts[token] = term_counts.get(token, 0) + 1
        collection_freqs[token] = collection_freqs.get(token, 0) + 1
    for token, freq in term_counts.items():
        postings.setdefault(token, {})[docid] = freq

index = {
    'postings': postings,
    'doc_lengths': doc_lengths,
    'num_docs': len(documents),
    'avg_doc_length': total_terms / len(documents),
    'total_terms': total_terms,
    'collection_freqs': collection_freqs,
}

with open('/app/index.json', 'w') as f:
    json.dump(index, f)

# ---- Queries ----
queries = [
    ("1", "information retrieval ranking relevance models"),
    ("2", "neural network deep learning training optimization"),
    ("3", "distributed database query processing optimization"),
    ("4", "virtual memory page replacement operating system"),
    ("5", "public key encryption digital signature cryptography"),
    ("6", "inverted index data structures search engines"),
    ("7", "machine learning classification prediction algorithms"),
    ("8", "concurrency synchronization deadlock operating systems"),
]

with open('/app/queries.tsv', 'w') as f:
    for qid, text in queries:
        f.write(f"{qid}\t{text}\n")

# ---- Qrels ----
qrels_data = [
    ("1", "doc001", 2), ("1", "doc002", 2), ("1", "doc005", 2),
    ("1", "doc006", 1), ("1", "doc009", 1), ("1", "doc010", 1),
    ("1", "doc007", 1), ("1", "doc004", 1),
    ("2", "doc011", 2), ("2", "doc012", 2), ("2", "doc019", 2),
    ("2", "doc013", 1), ("2", "doc020", 1), ("2", "doc017", 1),
    ("2", "doc018", 1),
    ("3", "doc025", 2), ("3", "doc022", 2), ("3", "doc027", 2),
    ("3", "doc026", 1), ("3", "doc029", 1), ("3", "doc021", 1),
    ("4", "doc031", 2), ("4", "doc032", 2), ("4", "doc039", 2),
    ("4", "doc036", 1), ("4", "doc033", 1),
    ("5", "doc041", 2), ("5", "doc044", 2), ("5", "doc042", 1),
    ("5", "doc045", 1), ("5", "doc043", 1), ("5", "doc046", 1),
    ("6", "doc004", 2), ("6", "doc007", 2), ("6", "doc023", 1),
    ("6", "doc030", 1), ("6", "doc002", 1),
    ("7", "doc014", 2), ("7", "doc015", 2), ("7", "doc016", 1),
    ("7", "doc013", 1), ("7", "doc011", 1),
    ("8", "doc037", 2), ("8", "doc040", 2), ("8", "doc024", 1),
    ("8", "doc035", 1), ("8", "doc033", 1),
]

with open('/app/qrels.txt', 'w') as f:
    for qid, docid, rel in qrels_data:
        f.write(f"{qid} 0 {docid} {rel}\n")

loaded_queries = list(queries)

# ---- Baselines ----

# Run A: BM25 with severely truncated result list (only 3 hits per query)
# Simulates a misconfigured retrieval depth limit
results_A = search_bm25(index, loaded_queries, k1=0.9, b=0.4, hits=3)
write_run(results_A, '/app/runs/run_A.txt', 'runA')

# Run B: BM25 with default parameters but missing queries 3, 7, 8
results_B_full = search_bm25(index, loaded_queries, k1=0.9, b=0.4, hits=1000)
results_B = {qid: docs for qid, docs in results_B_full.items()
             if qid not in ('3', '7', '8')}
write_run(results_B, '/app/runs/run_B.txt', 'runB')

# Run C: Query Likelihood with Dirichlet smoothing (wrong retrieval model)
results_C = search_qld(index, loaded_queries, mu=1000, hits=1000)
write_run(results_C, '/app/runs/run_C.txt', 'runC')

# ---- Compute targets ----
qrels_loaded = load_qrels('/app/qrels.txt')

# Find optimal BM25 configuration
best_map = -1
best_k1, best_b = 0.9, 0.4
for k1 in [0.5, 0.7, 0.9, 1.0, 1.2, 1.5, 2.0]:
    for b_val in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        res = search_bm25(index, loaded_queries, k1=k1, b=b_val, hits=1000)
        write_run(res, '/tmp/_grid.txt', 'grid')
        run = load_run('/tmp/_grid.txt')
        m = compute_metrics(qrels_loaded, run, complete=True)
        if m['map'] > best_map:
            best_map = m['map']
            best_k1, best_b = k1, b_val

# Evaluate optimal
opt_res = search_bm25(index, loaded_queries, k1=best_k1, b=best_b, hits=1000)
write_run(opt_res, '/tmp/_opt.txt', 'opt')
opt_m = compute_metrics(qrels_loaded, load_run('/tmp/_opt.txt'), complete=True)

# Evaluate baselines
baseline_m = {}
for name in ['run_A', 'run_B', 'run_C']:
    run = load_run(f'/app/runs/{name}.txt')
    baseline_m[name] = compute_metrics(qrels_loaded, run, complete=True)

# Set targets: between best baseline and optimal for each metric
targets = {}
for k in ['map', 'ndcg_cut_10', 'recall_1000']:
    max_baseline = max(baseline_m[r][k] for r in baseline_m)
    targets[k] = round((max_baseline + opt_m[k]) / 2, 4)
    # Ensure target is strictly above all baselines
    if targets[k] <= max_baseline:
        targets[k] = round(max_baseline + 0.02, 4)
    # Ensure target is achievable by optimal
    if targets[k] > opt_m[k]:
        targets[k] = round(opt_m[k] - 0.01, 4)

with open('/app/targets.json', 'w') as f:
    json.dump(targets, f, indent=2)

# Cleanup
for tmp in ['/tmp/_grid.txt', '/tmp/_opt.txt']:
    if os.path.exists(tmp):
        os.remove(tmp)

# Verify
print(f"Corpus: {len(documents)} docs, {len(queries)} queries, {len(qrels_data)} judgments")
print(f"Optimal BM25: k1={best_k1}, b={best_b}")
print(f"Optimal: MAP={opt_m['map']:.4f} nDCG={opt_m['ndcg_cut_10']:.4f} R={opt_m['recall_1000']:.4f}")
print(f"Targets: {targets}")
for name, bm in baseline_m.items():
    meets = all(bm[k] >= targets[k] for k in targets)
    print(f"  {name}: MAP={bm['map']:.4f} nDCG={bm['ndcg_cut_10']:.4f} R={bm['recall_1000']:.4f} meets_all={meets}")
assert not any(all(bm[k] >= targets[k] for k in targets) for bm in baseline_m.values()), \
    "ERROR: a baseline meets all targets!"
assert all(opt_m[k] >= targets[k] for k in targets), \
    "ERROR: optimal BM25 does not meet all targets!"
print("Setup verified: no baseline meets all targets, optimal does.")
