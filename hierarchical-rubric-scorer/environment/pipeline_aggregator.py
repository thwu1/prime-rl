"""Judge score aggregation for leaf criteria."""

import numpy as np


def aggregate_judge_scores(scores_by_key, criteria_map, sample_ids, judge_ids, leaf_ids):
    """Aggregate multiple judge scores per leaf criterion per sample.

    Binary criteria use majority vote: 1.0 if more than half of judges
    score >= 0.5, else 0.0.
    Partial criteria use the median of all judge scores.
    """
    aggregated = {}
    for sample_id in sample_ids:
        for crit_id in leaf_ids:
            judge_scores = []
            for judge_id in judge_ids:
                key = (sample_id, judge_id, crit_id)
                if key in scores_by_key:
                    judge_scores.append(scores_by_key[key])

            if not judge_scores:
                aggregated[(sample_id, crit_id)] = 0.0
                continue

            crit = criteria_map[crit_id]
            if crit["score_type"] == "binary":
                n_pass = sum(1 for s in judge_scores if s >= 0.5)
                aggregated[(sample_id, crit_id)] = (
                    1.0 if n_pass > len(judge_scores) / 2 else 0.0
                )
            elif crit["score_type"] == "partial":
                aggregated[(sample_id, crit_id)] = float(np.median(judge_scores))

    return aggregated
