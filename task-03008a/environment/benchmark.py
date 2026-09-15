"""Benchmark the search engine on representative queries."""
import time
import sys

sys.path.insert(0, "/app")
from search_engine import SearchEngine

engine = SearchEngine()
print("Building index...")
t0 = time.time()
engine.build_index("/app/corpus.jsonl")
print(f"Index built in {time.time() - t0:.2f}s")
print(f"Corpus: {engine.N} documents, avg length {engine.avgdl:.1f} tokens")
print(f"Vocabulary: {len(engine.index)} unique terms")

queries = [
    ("single rare term", "rare42"),
    ("two rare terms", "rare200 rare300"),
    ("stopword + rare", "the rare42"),
    ("two stopwords + rare", "the of rare42"),
    ("mixed 5-term", "the of word5 word10 rare42"),
    ("all stopwords (4)", "the of and to"),
    ("long mixed (10 terms)", "the of in word1 word5 word10 word20 rare50 rare100 rare200"),
    ("all stopwords (10)", "a is the of and in to for on that"),
]

print(f"\n{'Label':.<55} {'Time':>8} {'Postings':>10} {'Top-1 doc':>10}")
print("-" * 87)

for label, q in queries:
    t0 = time.time()
    results = engine.search(q, top_k=10)
    elapsed = (time.time() - t0) * 1000
    stats = engine.get_search_stats()
    top_doc = str(results[0][0]) if results else "-"
    print(
        f"{label + ' [' + q[:30] + ']':.<55} "
        f"{elapsed:>7.1f}ms {stats['postings_scored']:>10} {top_doc:>10}"
    )
