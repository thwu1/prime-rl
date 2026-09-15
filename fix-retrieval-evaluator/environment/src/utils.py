"""Data loading utilities for retrieval evaluation."""
import json


def load_queries(path):
    """Load queries from JSONL file.

    Each line should be a JSON object with fields:
    id, query, domain, gold_ids, excluded_ids, reasoning
    """
    queries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            # Only include queries that have reasoning annotations
            if entry.get("reasoning") is None:
                continue
            queries.append(entry)
    return queries


def load_corpus(path):
    """Load document corpus from JSONL file."""
    corpus = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            corpus[entry["id"]] = entry
    return corpus


def load_run(path):
    """Load retrieval run scores from JSON file.

    Returns {query_id: {doc_id: score}}
    """
    with open(path) as f:
        data = json.load(f)
    # Normalize scores to integer values for consistent comparison
    return {
        qid: {did: int(score) for did, score in docs.items()}
        for qid, docs in data.items()
    }
