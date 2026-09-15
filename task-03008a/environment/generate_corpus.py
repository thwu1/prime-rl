"""Generate a deterministic corpus for the block-max MAXSCORE search engine task."""
import random
import json

random.seed(42)

HIGH_FREQ = ["the", "of", "and", "to", "in", "a", "is", "for", "on", "that"]
MED_FREQ = [f"word{i}" for i in range(50)]
LOW_FREQ = [f"rare{i}" for i in range(500)]

NUM_DOCS = 50000

with open("/app/corpus.jsonl", "w") as f:
    for i in range(NUM_DOCS):
        length = random.randint(30, 300)
        terms = []
        for _ in range(length):
            r = random.random()
            if r < 0.35:
                terms.append(random.choice(HIGH_FREQ))
            elif r < 0.70:
                terms.append(random.choice(MED_FREQ))
            else:
                rank = (int(random.paretovariate(1.0)) - 1) % len(LOW_FREQ)
                terms.append(LOW_FREQ[rank])
        f.write(json.dumps({"id": i, "text": " ".join(terms)}) + "\n")

print(f"Generated {NUM_DOCS} documents to /app/corpus.jsonl")
