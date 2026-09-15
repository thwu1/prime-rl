#!/usr/bin/env python3
"""Generate synthetic IR evaluation data with embedded quality issues."""
import random
import json
import os

random.seed(42)

NUM_QUERIES = 40
NUM_DOCS = 300
TOP_K = 25
MAX_GRADE = 3
CATEGORIES = ["navigational", "informational", "transactional"]

os.makedirs('/app/data', exist_ok=True)

queries = [f"q{i:03d}" for i in range(1, NUM_QUERIES + 1)]
docs = [f"d{i:04d}" for i in range(1, NUM_DOCS + 1)]

# Assign queries to categories deterministically
query_categories = {}
for i, qid in enumerate(queries):
    query_categories[qid] = CATEGORIES[i % 3]

# Generate graded relevance judgments
qrels = {}
for qid in queries:
    num_judged = random.randint(20, 35)
    judged_docs = random.sample(docs, num_judged)
    qrels[qid] = {}
    for doc in judged_docs:
        grade = random.choices([0, 1, 2, 3], weights=[35, 30, 20, 15])[0]
        qrels[qid][doc] = grade

# Select query-doc pairs to duplicate with conflicting grades
dup_candidates = []
for qid in sorted(queries):
    for doc in sorted(qrels[qid]):
        grade = qrels[qid][doc]
        if 1 <= grade <= 2:
            dup_candidates.append((qid, doc, grade))

random.shuffle(dup_candidates)
duplicate_entries = []
for qid, doc, orig_grade in dup_candidates[:5]:
    new_grade = MAX_GRADE if orig_grade <= 1 else 0
    duplicate_entries.append((qid, doc, new_grade))

# Generate system runs with different retrieval characteristics
systems = ['bm25', 'tfidf', 'embedding', 'sparse', 'hybrid']
runs = {}
for sys_name in systems:
    runs[sys_name] = {}
    for qid in queries:
        judged = list(qrels[qid].keys())
        unjudged = [d for d in docs if d not in qrels[qid]]

        if sys_name == 'bm25':
            n_judged = min(random.randint(12, 16), len(judged))
            boost_lo, boost_hi = 0.5, 2.5
        elif sys_name == 'tfidf':
            n_judged = min(random.randint(10, 14), len(judged))
            boost_lo, boost_hi = 0.3, 2.0
        elif sys_name == 'embedding':
            n_judged = min(random.randint(8, 12), len(judged))
            boost_lo, boost_hi = 1.0, 3.5
        elif sys_name == 'sparse':
            n_judged = min(random.randint(10, 15), len(judged))
            boost_lo, boost_hi = 0.4, 1.8
        else:  # hybrid
            n_judged = min(random.randint(14, 18), len(judged))
            boost_lo, boost_hi = 0.8, 2.8

        sel_judged = random.sample(judged, n_judged)
        remaining = TOP_K - n_judged
        sel_unjudged = random.sample(unjudged, min(remaining, len(unjudged)))
        all_sel = sel_judged + sel_unjudged

        scored = []
        for doc in all_sel:
            s = random.uniform(1.0, 10.0)
            if doc in qrels[qid]:
                s += qrels[qid][doc] * random.uniform(boost_lo, boost_hi)
            scored.append((doc, s))

        scored.sort(key=lambda x: (-x[1], x[0]))
        runs[sys_name][qid] = [(doc, r + 1, sc) for r, (doc, sc) in enumerate(scored)]

# Generate click data with position bias (examination hypothesis)
clicks = []
for qid in queries:
    for doc, rank, _ in runs['bm25'][qid][:15]:
        exam = 1.0 / rank
        if doc in qrels[qid]:
            rel = qrels[qid][doc] / MAX_GRADE
        else:
            rel = 0.05
        p_click = exam * rel
        n_imp = random.randint(5, 15)
        for _ in range(n_imp):
            clicks.append((qid, doc, rank, 1 if random.random() < p_click else 0))

# Add invalid click entries with position=0
num_invalid = 12
for _ in range(num_invalid):
    qid = random.choice(queries)
    doc = random.choice(docs)
    clicks.append((qid, doc, 0, random.randint(0, 1)))

random.shuffle(clicks)

# Write qrels (TREC format) with duplicates appended at end
with open('/app/data/qrels.txt', 'w') as f:
    for qid in sorted(qrels):
        for doc in sorted(qrels[qid]):
            f.write(f"{qid} 0 {doc} {qrels[qid][doc]}\n")
    # Append duplicate entries with conflicting grades
    for qid, doc, new_grade in duplicate_entries:
        f.write(f"{qid} 0 {doc} {new_grade}\n")

# Write run files (TREC format)
for sn in systems:
    with open(f'/app/data/{sn}.run', 'w') as f:
        for qid in sorted(runs[sn]):
            for doc, rank, sc in runs[sn][qid]:
                f.write(f"{qid} Q0 {doc} {rank} {sc:.6f} {sn}\n")

# Write click log
with open('/app/data/clicks.tsv', 'w') as f:
    f.write("query_id\tdoc_id\tposition\tclicked\n")
    for qid, doc, pos, cl in clicks:
        f.write(f"{qid}\t{doc}\t{pos}\t{cl}\n")

# Write query taxonomy
with open('/app/data/query_taxonomy.json', 'w') as f:
    json.dump(query_categories, f, indent=2)

# Write data README with conventions
readme_text = (
    "Search Evaluation Data\n"
    "=" * 40 + "\n"
    "Queries: {nq}\n"
    "Documents: {nd}\n"
    "Systems: {sys}\n"
    "Relevance grades: 0 (irrelevant) to {mg} (highly relevant)\n"
    "Results per query per system: up to {tk}\n"
    "Click log entries: {nc}\n"
    "Query categories: {cats}\n"
    "\n"
    "Notes:\n"
    "- Multiple annotators may have judged the same query-document pair.\n"
    "  For such cases, the most generous (maximum) grade should be used.\n"
    "- Click data was collected from a production system with position-based\n"
    "  display. Click positions are 1-indexed (position 1 = top of page).\n"
).format(
    nq=len(queries), nd=len(docs), sys=', '.join(systems),
    mg=MAX_GRADE, tk=TOP_K, nc=len(clicks), cats=', '.join(CATEGORIES)
)

with open('/app/data/README.txt', 'w') as f:
    f.write(readme_text)

print("Data generation complete.")
print(f"Queries: {len(queries)}, Docs: {len(docs)}")
print(f"Systems: {', '.join(systems)}")
print(f"Total judgments: {sum(len(v) for v in qrels.values())}")
print(f"Duplicate qrel entries: {len(duplicate_entries)}")
print(f"Click entries: {len(clicks)} (including {num_invalid} invalid)")
