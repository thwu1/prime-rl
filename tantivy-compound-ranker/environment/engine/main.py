#!/usr/bin/env python3
"""Search engine entry point. Reads corpus from SQLite, runs queries, writes results."""

import json
import sys

sys.path.insert(0, "/app")

from engine.db_reader import read_corpus
from engine.indexer import InvertedIndex
from engine.scorer import BM25Scorer
from engine.searcher import Searcher


def main():
    corpus = read_corpus("/app/data/corpus.db")

    with open("/app/data/queries.json") as f:
        queries = json.load(f)

    with open("/app/engine/config.json") as f:
        config = json.load(f)

    fields = config["fields"]
    field_boosts = config["field_boosts"]

    # Build inverted index
    index = InvertedIndex()
    index.build(corpus, fields)

    # Create scorer
    scorer = BM25Scorer(k1=config["k1"], b=config["b"], num_docs=index.num_docs)

    # Create searcher
    searcher = Searcher(index, scorer, field_boosts)

    # Execute queries
    results = {}
    for query_text in queries:
        ranked = searcher.search(query_text, top_k=10)
        results[query_text] = [
            {"doc_id": doc_id, "score": round(score, 6), "title": title}
            for doc_id, score, title in ranked
        ]

    # Write output
    with open("/app/output.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
