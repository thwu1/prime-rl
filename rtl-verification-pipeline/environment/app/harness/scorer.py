"""Computes mutation adequacy score."""


def compute_adequacy(results):
    """Compute the mutation adequacy score.

    Correct formula: killed / (total - equivalent)
    Equivalent mutants must be excluded from the denominator.
    """
    total = len(results)
    killed = sum(1 for r in results if r["status"] == "KILLED")
    equivalent = sum(1 for r in results if r["equivalent"])

    if total == 0:
        score = 0.0
    else:
        score = killed / total

    return {
        "total_mutants": total,
        "killed": killed,
        "equivalent": equivalent,
        "adequacy_score": score,
    }
