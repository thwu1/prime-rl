#!/usr/bin/env python3
"""Generate synthetic MS MARCO-style passage ranking data for IR evaluation task."""
import random
import json
import os
from collections import defaultdict

random.seed(20240315)

TOPICS = [
    {"name": "photosynthesis", "terms": ["chlorophyll", "thylakoid", "stomata", "rubisco", "nadph", "photosystem", "carotenoid", "stroma", "granum", "photorespiration", "plastoquinone", "ferredoxin"]},
    {"name": "thermodynamics", "terms": ["entropy", "enthalpy", "carnot", "adiabatic", "isothermal", "clausius", "boltzmann", "exothermic", "endothermic", "isobaric", "fugacity", "helmholtz"]},
    {"name": "machinelearning", "terms": ["backpropagation", "overfitting", "regularization", "dropout", "convolution", "transformer", "attention", "batchnorm", "softmax", "embedding", "autoencoder", "perceptron"]},
    {"name": "genetics", "terms": ["allele", "genotype", "phenotype", "chromosome", "meiosis", "epigenetic", "heterozygous", "codon", "ribosome", "polymerase", "telomere", "nucleotide"]},
    {"name": "cryptography", "terms": ["encryption", "cipher", "ciphertext", "nonce", "plaintext", "keystream", "diffie", "hmac", "blockcipher", "streamcipher", "substitution", "permutation"]},
    {"name": "ecology", "terms": ["ecosystem", "biodiversity", "trophic", "symbiosis", "biomass", "niche", "succession", "mutualism", "commensalism", "biome", "detritivore", "eutrophication"]},
    {"name": "organicchemistry", "terms": ["carbonyl", "hydroxyl", "nucleophilic", "chirality", "saponification", "esterification", "aldehyde", "ketone", "alkene", "stereoisomer", "enantiomer", "racemization"]},
    {"name": "astrophysics", "terms": ["neutronstar", "quasar", "pulsar", "accretion", "redshift", "supernova", "magnetar", "protostar", "chromosphere", "parallax", "luminosity", "spectrograph"]},
    {"name": "neuroscience", "terms": ["synapse", "neurotransmitter", "hippocampus", "dopamine", "myelin", "axon", "dendrite", "serotonin", "glia", "cortex", "amygdala", "cerebellum"]},
    {"name": "geophysics", "terms": ["tectonic", "seismic", "subduction", "lithosphere", "mantle", "isostatic", "asthenosphere", "mohorovicic", "geothermal", "magnetometer", "gravimetry", "paleomagnetic"]},
]

FILLERS = [
    "the", "is", "a", "of", "in", "and", "to", "that", "for", "with",
    "this", "from", "on", "an", "by", "which", "can", "be", "has", "are",
    "its", "process", "system", "method", "approach", "technique",
    "analysis", "study", "model", "based", "using", "through",
    "important", "significant", "fundamental", "related", "known",
    "involves", "requires", "produces", "measures", "determines"
]

os.makedirs("/app/data", exist_ok=True)
os.makedirs("/app/eval/reference_runs", exist_ok=True)

# === Generate passages: 50 per topic = 500 total ===
passages = []
passage_texts = {}

for topic_idx, topic in enumerate(TOPICS):
    terms = topic["terms"]
    for p_idx in range(50):
        pid = topic_idx * 50 + p_idx + 1
        rng = random.Random(pid * 7919 + 1013)

        n_terms = rng.randint(3, min(7, len(terms)))
        selected_terms = rng.sample(terms, n_terms)

        words = []
        for term in selected_terms:
            n_fill = rng.randint(2, 4)
            for _ in range(n_fill):
                words.append(rng.choice(FILLERS))
            words.append(term)
        for _ in range(rng.randint(1, 3)):
            words.append(rng.choice(FILLERS))

        text = " ".join(words)
        passages.append((pid, text))
        passage_texts[pid] = text

# === Generate queries (4 per topic = 40) and qrels ===
queries = []
qrels_list = []
query_relevant = {}

for topic_idx, topic in enumerate(TOPICS):
    terms = topic["terms"]
    for q_idx in range(4):
        qid = topic_idx * 4 + q_idx + 1
        rng = random.Random(qid * 3571 + 997)

        n_q = rng.randint(2, 3)
        query_terms = rng.sample(terms, n_q)
        query_text = " ".join(query_terms)
        queries.append((qid, query_text))

        # Find best matching passage by exact token overlap
        topic_pids = range(topic_idx * 50 + 1, topic_idx * 50 + 51)
        best_pid = None
        best_score = -1
        for pid in topic_pids:
            p_tokens = set(passage_texts[pid].lower().split())
            score = sum(1 for t in query_terms if t.lower() in p_tokens)
            if score > best_score or (score == best_score and (best_pid is None or pid < best_pid)):
                best_score = score
                best_pid = pid

        query_relevant[qid] = best_pid
        qrels_list.append((qid, 0, best_pid, 1))

# === Generate top-100 candidates per query ===
candidates = []
candidates_by_qid = defaultdict(list)

for qid, query_text in queries:
    topic_idx = (qid - 1) // 4
    relevant_pid = query_relevant[qid]
    rng = random.Random(qid * 4903 + 2011)

    same_topic = [p for p in range(topic_idx * 50 + 1, topic_idx * 50 + 51) if p != relevant_pid]
    other_topic = [p[0] for p in passages if (p[0] - 1) // 50 != topic_idx]

    n_same = min(49, len(same_topic))
    n_other = 99 - n_same

    selected = rng.sample(same_topic, n_same) + rng.sample(other_topic, n_other) + [relevant_pid]
    rng.shuffle(selected)

    for pid in selected:
        candidates.append((qid, pid, query_text, passage_texts[pid]))
        candidates_by_qid[qid].append(pid)

# === Write data files ===
with open("/app/data/collection.tsv", "w") as f:
    for pid, text in passages:
        f.write(f"{pid}\t{text}\n")

with open("/app/data/queries.tsv", "w") as f:
    for qid, text in queries:
        f.write(f"{qid}\t{text}\n")

with open("/app/data/qrels.tsv", "w") as f:
    for row in qrels_list:
        f.write(f"{row[0]}\t{row[1]}\t{row[2]}\t{row[3]}\n")

with open("/app/data/top100.tsv", "w") as f:
    for row in candidates:
        f.write(f"{row[0]}\t{row[1]}\t{row[2]}\t{row[3]}\n")

# === Generate reference runs ===
extra_qids = list(range(41, 51))

# Run 1: Random ordering (50 queries: 40 judged + 10 extra)
rng_r = random.Random(42)
with open("/app/eval/reference_runs/random_run.tsv", "w") as f:
    for qid in sorted(candidates_by_qid.keys()):
        pids = candidates_by_qid[qid][:]
        rng_r.shuffle(pids)
        for rank, pid in enumerate(pids, 1):
            f.write(f"{qid}\t{pid}\t{rank}\n")
    for eq in extra_qids:
        dummy = rng_r.sample(range(1, 501), 50)
        for rank, pid in enumerate(dummy, 1):
            f.write(f"{eq}\t{pid}\t{rank}\n")

# Run 2: Oracle (40 queries, relevant always at rank 1)
with open("/app/eval/reference_runs/oracle_run.tsv", "w") as f:
    for qid in sorted(candidates_by_qid.keys()):
        relevant = query_relevant[qid]
        others = [p for p in candidates_by_qid[qid] if p != relevant]
        f.write(f"{qid}\t{relevant}\t1\n")
        for rank, pid in enumerate(others, 2):
            f.write(f"{qid}\t{pid}\t{rank}\n")

# Run 3: Partial (45 queries: 40 judged + 5 extra, relevant at cycling ranks)
target_ranks = [1, 3, 5, 7, 9, 2, 4, 6, 8, 10] * 4
with open("/app/eval/reference_runs/partial_run.tsv", "w") as f:
    for idx, qid in enumerate(sorted(candidates_by_qid.keys())):
        relevant = query_relevant[qid]
        others = [p for p in candidates_by_qid[qid] if p != relevant]
        tr = target_ranks[idx]
        ordered = others[:tr - 1] + [relevant] + others[tr - 1:]
        for rank, pid in enumerate(ordered[:100], 1):
            f.write(f"{qid}\t{pid}\t{rank}\n")
    rng_p = random.Random(123)
    for eq in extra_qids[:5]:
        dummy = rng_p.sample(range(1, 501), 50)
        for rank, pid in enumerate(dummy, 1):
            f.write(f"{eq}\t{pid}\t{rank}\n")

# === Compute correct reference scores ===

def correct_mrr10(qrels_dict, run_file):
    """Correct MRR@10 computation."""
    qid_to_ranked = {}
    with open(run_file) as f:
        for line in f:
            parts = line.strip().split('\t')
            qid, pid, rank = int(parts[0]), int(parts[1]), int(parts[2])
            if qid not in qid_to_ranked:
                qid_to_ranked[qid] = [0] * 1000
            qid_to_ranked[qid][rank - 1] = pid

    mrr = 0.0
    for qid in qid_to_ranked:
        if qid in qrels_dict:
            for i in range(10):
                if qid_to_ranked[qid][i] in qrels_dict[qid]:
                    mrr += 1.0 / (i + 1)
                    break
    return mrr / len(qrels_dict)

qrels_dict = {}
for qid, _, pid, _ in qrels_list:
    if qid not in qrels_dict:
        qrels_dict[qid] = []
    qrels_dict[qid].append(pid)

ref_scores = {}
for name in ["random_run", "oracle_run", "partial_run"]:
    ref_scores[name] = correct_mrr10(qrels_dict, f"/app/eval/reference_runs/{name}.tsv")

with open("/app/eval/reference_scores.json", "w") as f:
    json.dump(ref_scores, f, indent=2)

print(f"Generated {len(passages)} passages, {len(queries)} queries")
print(f"Reference scores: {json.dumps(ref_scores, indent=2)}")
