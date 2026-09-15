"""Utilities for reading and writing TREC-format files."""


def load_trec_run(path):
    """Load a TREC run file into {qid: {docid: score}} format.

    Standard TREC run format: qid Q0 docid rank score run_name
    """
    results = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 6:
                continue
            qid = parts[0]
            docid = parts[2]
            score = float(parts[4])  # Column index 4 = score
            results.setdefault(qid, {})[docid] = score
    return results


def load_trec_qrels(path):
    """Load TREC qrels file into {qid: {docid: relevance}} format.

    Standard TREC qrels format: qid iteration docid relevance
    """
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            qid = parts[0]
            docid = parts[2]
            rel = int(parts[3])
            qrels.setdefault(qid, {})[docid] = rel
    return qrels


def write_trec_run(results, path, run_name="fused"):
    """Write results in TREC run format."""
    lines = []
    for qid in sorted(results.keys()):
        ranked = sorted(results[qid].items(), key=lambda x: x[1], reverse=True)
        for rank, (docid, score) in enumerate(ranked, 1):
            lines.append(f"{qid} Q0 {docid} {rank} {score:.6f} {run_name}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
