"""Rank fusion methods for combining retrieval system results."""


def minmax_normalize(doc_scores):
    """Min-max normalize scores to [0, 1] per query."""
    if len(doc_scores) <= 1:
        return [(d, 1.0) for d, s in doc_scores]
    scores = [s for _, s in doc_scores]
    mn, mx = min(scores), max(scores)
    if mx == mn:
        return [(d, 1.0) for d, s in doc_scores]
    return [(d, (s - mn) / (mx - mn)) for d, s in doc_scores]


def rrf_fuse(system_runs_list, qids, k=60):
    """Reciprocal Rank Fusion."""
    fused = {}
    for qid in qids:
        scores = {}
        for sys_runs in system_runs_list:
            if qid not in sys_runs:
                continue
            for rank, (doc_id, _) in enumerate(sys_runs[qid]):
                scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank)
        fused[qid] = sorted(scores.items(), key=lambda x: -x[1])
    return fused


def combsum_fuse(system_runs_list, qids, weights):
    """CombSUM: weighted combination of min-max normalized scores."""
    fused = {}
    for qid in qids:
        scores = {}
        for idx, sys_runs in enumerate(system_runs_list):
            if qid not in sys_runs:
                continue
            normed = minmax_normalize(sys_runs[qid])
            w = weights[idx]
            for doc_id, nscore in normed:
                scores[doc_id] = scores.get(doc_id, 0) + w * nscore
        fused[qid] = sorted(scores.items(), key=lambda x: -x[1])
    return fused


def combmnz_fuse(system_runs_list, qids):
    """CombMNZ: sum of normalized scores times count of systems returning doc."""
    fused = {}
    for qid in qids:
        scores = {}
        counts = {}
        for sys_runs in system_runs_list:
            if qid not in sys_runs:
                continue
            normed = minmax_normalize(sys_runs[qid])
            for doc_id, nscore in normed:
                scores[doc_id] = scores.get(doc_id, 0) + nscore
                counts[doc_id] = counts.get(doc_id, 0) + 1
        fused[qid] = sorted(
            [(d, scores[d] * counts[d]) for d in scores],
            key=lambda x: -x[1]
        )
    return fused
