"""Data loading and preprocessing for the evaluation pipeline."""

import json


def load_rubric(path):
    """Load rubric definition from JSON file."""
    with open(path) as f:
        return json.load(f)


def load_judgments(path):
    """Load judgment entries from JSONL file."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def deduplicate_and_filter(entries, valid_criterion_ids):
    """Deduplicate judgment entries and filter out invalid criteria.

    For entries sharing the same (sample_id, judge_id, criterion_id) key,
    retains one canonical entry. Entries referencing criteria not present
    in the rubric are discarded.
    """
    seen = set()
    deduped = {}
    for entry in entries:
        cid = entry["criterion_id"]
        if cid not in valid_criterion_ids:
            continue
        key = (entry["sample_id"], entry["judge_id"], cid)
        if key in seen:
            continue
        seen.add(key)
        deduped[key] = entry["score"]
    return deduped
