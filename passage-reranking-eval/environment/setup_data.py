#!/usr/bin/env python3
"""
Generate a synthetic MS MARCO-format passage ranking dataset stored in SQLite.
Also generates flat-file baseline runs and qrels for evaluation.
All data is deterministic (seed=42).

Produces:
  /app/data/corpus.db           - SQLite with tables: collection, queries, qrels, candidates
  /app/data/qrels.tsv           - TREC-format relevance judgments (flat file)
  /app/data/runs/random_run.tsv - Random baseline run
  /app/data/runs/tfidf_run.tsv  - TF-IDF overlap baseline run
  /app/data/runs/oracle_run.tsv - Oracle baseline run (relevant always rank 1)
"""


import random
import os
import sqlite3

random.seed(42)

DATA_DIR = "/app/data"
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "runs"), exist_ok=True)

TOPICS = {
    "medicine": [
        "diagnosis", "treatment", "patient", "hospital", "surgery", "symptom",
        "disease", "therapy", "clinical", "doctor", "health", "recovery",
        "prescription", "infection", "chronic", "acute", "prognosis",
        "pathology", "oncology", "cardiology", "anatomy", "pharmaceutical",
        "radiology", "immunology", "neurology"
    ],
    "computing": [
        "algorithm", "software", "hardware", "network", "database",
        "programming", "server", "cloud", "encryption", "protocol",
        "compiler", "debugging", "kernel", "thread", "cache", "recursion",
        "parsing", "binary", "runtime", "virtualization", "middleware",
        "bandwidth", "latency", "throughput", "microservice"
    ],
    "legal": [
        "court", "judge", "attorney", "statute", "plaintiff", "defendant",
        "verdict", "jurisdiction", "testimony", "evidence", "lawsuit",
        "appeal", "legislation", "regulation", "compliance", "arbitration",
        "indictment", "deposition", "subpoena", "precedent", "litigation",
        "tort", "felony", "misdemeanor", "jurisprudence"
    ],
    "physics": [
        "quantum", "particle", "energy", "momentum", "wavelength", "spectrum",
        "gravity", "relativity", "neutron", "proton", "electron", "photon",
        "velocity", "acceleration", "thermodynamics", "entropy", "radiation",
        "magnetic", "oscillation", "diffraction", "refraction", "amplitude",
        "frequency", "capacitance", "inductance"
    ],
    "finance": [
        "investment", "portfolio", "dividend", "equity", "liability",
        "revenue", "depreciation", "inflation", "mortgage", "collateral",
        "derivative", "arbitrage", "liquidity", "volatility", "amortization",
        "hedging", "yield", "bonds", "securities", "valuation", "futures",
        "options", "leverage", "capital", "insolvency"
    ],
    "biology": [
        "organism", "chromosome", "mitosis", "protein", "enzyme", "mutation",
        "genome", "phenotype", "metabolism", "photosynthesis", "respiration",
        "membrane", "organelle", "nucleus", "ribosome", "transcription",
        "translation", "allele", "genotype", "homeostasis", "symbiosis",
        "ecology", "biodiversity", "adaptation", "speciation"
    ],
    "chemistry": [
        "oxidation", "reduction", "solvent", "precipitate", "distillation",
        "titration", "reagent", "buffer", "concentration", "crystallization",
        "polymerization", "stoichiometry", "valence", "covalent", "ionic",
        "electrolysis", "catalyst", "isomer", "molarity", "sublimation",
        "hydrolysis", "saponification", "alkylation", "esterification",
        "chromatography"
    ],
    "geology": [
        "tectonic", "sediment", "erosion", "volcanic", "mineral", "fossil",
        "stratigraphy", "magma", "metamorphic", "igneous", "seismic",
        "aquifer", "glacial", "limestone", "basalt", "geothermal",
        "continental", "subduction", "weathering", "crystalline", "alluvial",
        "karst", "moraine", "stalactite", "lithosphere"
    ],
    "linguistics": [
        "morphology", "syntax", "phonology", "semantics", "pragmatics",
        "lexicon", "grammar", "dialect", "prosody", "inflection",
        "derivation", "consonant", "vowel", "syllable", "morpheme",
        "phoneme", "clause", "predicate", "auxiliary", "conjunction",
        "adverb", "pronoun", "gerund", "participle", "subjunctive"
    ],
    "economics": [
        "elasticity", "equilibrium", "monopoly", "oligopoly", "externality",
        "subsidy", "tariff", "marginal", "utility", "scarcity", "surplus",
        "deficit", "monetary", "fiscal", "macroeconomic", "microeconomic",
        "aggregate", "consumption", "production", "distribution",
        "stagflation", "hyperinflation", "recession", "depression",
        "mercantilism"
    ],
}

FILLER = [
    "the", "a", "of", "in", "to", "and", "is", "for", "on", "with",
    "that", "by", "from", "as", "are", "was", "an", "this", "be", "which",
    "or", "at", "has", "can", "its", "may", "also", "more", "these",
    "other", "some", "their", "been", "have", "used", "such", "often",
    "through", "between", "about", "each", "into", "over", "process",
    "system", "method", "approach", "study", "analysis", "research",
    "field", "area", "important", "significant", "common", "specific",
    "general", "particular", "various", "different", "related", "complex",
    "standard", "primary", "major", "key", "main", "basic", "critical",
    "essential", "fundamental", "traditional", "modern", "recent",
    "current", "new", "advanced", "experimental", "theoretical",
    "practical", "applied", "technical", "detailed", "comprehensive"
]

topic_names = list(TOPICS.keys())


def make_passage(terms_list):
    """Build passage text from a list of domain terms, interspersed with filler."""
    random.shuffle(terms_list)
    words = []
    for i, t in enumerate(terms_list):
        if i > 0 and random.random() < 0.45:
            words.append(random.choice(FILLER))
        words.append(t)
        if random.random() < 0.35:
            words.append(random.choice(FILLER))
    extra = random.randint(5, 20)
    for _ in range(extra):
        pos = random.randint(0, len(words))
        words.insert(pos, random.choice(FILLER))
    return " ".join(words)


# ── Phase 1: generate background passages (1800 total, 180 per topic) ────────

passages = {}   # pid -> (topic, text)
pid_counter = 1

for topic in topic_names:
    vocab = TOPICS[topic]
    for _ in range(180):
        n_primary = random.randint(8, 16)
        primary_terms = random.sample(vocab, min(n_primary, len(vocab)))
        sec_topic = random.choice([t for t in topic_names if t != topic])
        n_sec = random.randint(2, 7) if random.random() < 0.5 else 0
        sec_terms = random.sample(
            TOPICS[sec_topic], min(n_sec, len(TOPICS[sec_topic]))
        ) if n_sec else []
        text = make_passage(primary_terms + sec_terms)
        passages[pid_counter] = (topic, text)
        pid_counter += 1

# ── Phase 2: generate queries and their relevant passages (200 queries) ──────

queries = {}       # qid -> (topic, text)
qrels = {}         # qid -> pid
candidates = {}    # qid -> list of 100 pids

qid_counter = 100001

for topic in topic_names:
    vocab = TOPICS[topic]
    topic_bg_pids = [p for p, (t, _) in passages.items() if t == topic]
    other_pids = [p for p, (t, _) in passages.items() if t != topic]

    for q_idx in range(20):
        n_q = random.randint(3, 4)
        q_terms = random.sample(vocab, n_q)

        # Mixed-case query: capitalize every other term starting with first
        q_words = [
            w.capitalize() if i % 2 == 0 else w
            for i, w in enumerate(q_terms)
        ]
        q_text = " ".join(q_words)

        # Build relevant passage guaranteed to contain ALL query terms (lowercase)
        remaining_topic = [w for w in vocab if w not in q_terms]
        extra_topic = random.sample(
            remaining_topic,
            min(random.randint(6, 12), len(remaining_topic))
        )
        sec_topic = random.choice([t for t in topic_names if t != topic])
        sec_terms = random.sample(TOPICS[sec_topic], random.randint(2, 5))
        rel_text = make_passage(list(q_terms) + extra_topic + sec_terms)
        rel_pid = pid_counter
        passages[rel_pid] = (topic, rel_text)
        pid_counter += 1

        # Build candidate set: relevant + 12 same-topic bg + 87 other-topic bg
        n_same = min(12, len(topic_bg_pids))
        n_other = 99 - n_same
        same_cands = random.sample(topic_bg_pids, n_same)
        other_cands = random.sample(other_pids, n_other)
        cand_list = [rel_pid] + same_cands + other_cands
        random.shuffle(cand_list)

        queries[qid_counter] = (topic, q_text)
        qrels[qid_counter] = rel_pid
        candidates[qid_counter] = cand_list
        qid_counter += 1

# ── Phase 3: write to SQLite database ────────────────────────────────────────

db_path = os.path.join(DATA_DIR, "corpus.db")
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("CREATE TABLE collection (pid INTEGER PRIMARY KEY, text TEXT)")
c.execute("CREATE TABLE queries (qid INTEGER PRIMARY KEY, text TEXT)")
c.execute("CREATE TABLE qrels (qid INTEGER, iter INTEGER, pid INTEGER, rel INTEGER)")
c.execute("CREATE TABLE candidates (qid INTEGER, pid INTEGER)")
c.execute("CREATE INDEX idx_candidates_qid ON candidates(qid)")
c.execute("CREATE INDEX idx_candidates_pid ON candidates(pid)")

for pid in sorted(passages.keys()):
    c.execute("INSERT INTO collection VALUES (?, ?)", (pid, passages[pid][1]))

for qid in sorted(queries.keys()):
    c.execute("INSERT INTO queries VALUES (?, ?)", (qid, queries[qid][1]))

for qid in sorted(qrels.keys()):
    c.execute("INSERT INTO qrels VALUES (?, ?, ?, ?)", (qid, 0, qrels[qid], 1))

for qid in sorted(candidates.keys()):
    for pid in candidates[qid]:
        c.execute("INSERT INTO candidates VALUES (?, ?)", (qid, pid))

conn.commit()
conn.close()

# ── Phase 4: write flat-file qrels for evaluation script ─────────────────────

with open(os.path.join(DATA_DIR, "qrels.tsv"), "w") as f:
    for qid in sorted(qrels.keys()):
        f.write(f"{qid}\t0\t{qrels[qid]}\t1\n")

# ── Phase 5: generate baseline runs as flat files ────────────────────────────

# 1. Random baseline (candidates in their shuffled order)
with open(os.path.join(DATA_DIR, "runs", "random_run.tsv"), "w") as f:
    for qid in sorted(candidates.keys()):
        for rank, pid in enumerate(candidates[qid], 1):
            f.write(f"{qid}\t{pid}\t{rank}\n")


# 2. TF overlap baseline (raw count of query terms in passage, case-insensitive)
def tf_overlap(query_text, passage_text):
    qt = set(query_text.lower().split())
    pt = passage_text.lower().split()
    return sum(1 for w in pt if w in qt)


with open(os.path.join(DATA_DIR, "runs", "tfidf_run.tsv"), "w") as f:
    for qid in sorted(candidates.keys()):
        q_text = queries[qid][1]
        scored = []
        for pid in candidates[qid]:
            score = tf_overlap(q_text, passages[pid][1])
            scored.append((pid, score))
        scored.sort(key=lambda x: (-x[1], x[0]))
        for rank, (pid, _) in enumerate(scored, 1):
            f.write(f"{qid}\t{pid}\t{rank}\n")

# 3. Oracle baseline (relevant passage always at rank 1)
with open(os.path.join(DATA_DIR, "runs", "oracle_run.tsv"), "w") as f:
    for qid in sorted(candidates.keys()):
        rel = qrels[qid]
        rest = [pid for pid in candidates[qid] if pid != rel]
        f.write(f"{qid}\t{rel}\t1\n")
        for rank, pid in enumerate(rest, 2):
            f.write(f"{qid}\t{pid}\t{rank}\n")

print(f"Generated {len(passages)} passages, {len(queries)} queries, "
      f"{sum(len(v) for v in candidates.values())} candidate entries")
print(f"SQLite database: {db_path}")
print(f"Flat-file qrels: {DATA_DIR}/qrels.tsv")
print(f"Baseline runs: {DATA_DIR}/runs/")
