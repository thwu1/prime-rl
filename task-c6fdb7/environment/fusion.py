"""Rank fusion methods for combining retrieval system results."""


def minmax_normalize(doc_scores):
    """Min-max normalize scores to [0, 1]."""
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
    """CombSUM with per-system weights and score normalization."""
    fused = {}

    # Compute score ranges per system across all queries
    global_ranges = []
    for sys_runs in system_runs_list:
        all_scores = []
        for qid in qids:
            if qid in sys_runs:
                all_scores.extend([s for _, s in sys_runs[qid]])
        if all_scores:
            global_ranges.append((min(all_scores), max(all_scores)))
        else:
            global_ranges.append((0, 1))

    for qid in qids:
        scores = {}
        for idx, sys_runs in enumerate(system_runs_list):
            if qid not in sys_runs:
                continue
            mn, mx = global_ranges[idx]
            w = weights[idx]
            for doc_id, raw_score in sys_runs[qid]:
                if mx > mn:
                    nscore = (raw_score - mn) / (mx - mn)
                else:
                    nscore = 1.0
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
