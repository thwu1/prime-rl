#!/usr/bin/env python3
"""Generate a synthetic corpus with Zipfian term distributions.

Produces a deterministic corpus for the block-max MAXSCORE benchmark task.
Terms follow Zipf's law: term i has relative frequency proportional to 1/(i+1).
"""
import bisect
import json
import os
import random

SEED = 42
NUM_DOCS = 20000
VOCAB_SIZE = 8000
MIN_DOC_LENGTH = 50
MAX_DOC_LENGTH = 300
OUTPUT_DIR = "/app/data"


def main():
    random.seed(SEED)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Build cumulative Zipfian distribution for sampling
    cum_weights = []
    running = 0.0
    for i in range(VOCAB_SIZE):
        running += 1.0 / (i + 1)
        cum_weights.append(running)
    total_weight = cum_weights[-1]

    def sample_term():
        u = random.random() * total_weight
        return bisect.bisect_left(cum_weights, u)

    total_length = 0
    with open(os.path.join(OUTPUT_DIR, "documents.jsonl"), "w") as f:
        for doc_id in range(NUM_DOCS):
            doc_length = random.randint(MIN_DOC_LENGTH, MAX_DOC_LENGTH)
            total_length += doc_length
            terms = [f"t{sample_term()}" for _ in range(doc_length)]
            f.write(json.dumps({"id": doc_id, "terms": terms}) + "\n")

    avg_doc_length = total_length / NUM_DOCS

    with open(os.path.join(OUTPUT_DIR, "stats.json"), "w") as f:
        json.dump({
            "num_docs": NUM_DOCS,
            "avg_doc_length": avg_doc_length,
            "vocab_size": VOCAB_SIZE,
        }, f, indent=2)

    print(f"Generated {NUM_DOCS} documents, avg length {avg_doc_length:.1f}")


if __name__ == "__main__":
    main()
