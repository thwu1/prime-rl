"""Model ranking by aggregate robustness."""


def run(prior_results, config, taxonomy):
    """Rank models by their harmonic mean of category robustness scores.

    Takes category robustness scores from the robustness stage and computes
    a single aggregate score per model using the harmonic mean across all
    categories (both base and compound). Returns a list of {model, score}
    dicts sorted descending by score.
    """
    robustness = prior_results["robustness"]

    ranking = []
    for model, categories in robustness.items():
        scores = list(categories.values())
        n = len(scores)
        harmonic_mean = sum(scores) / n
        ranking.append({"model": model, "score": harmonic_mean})

    ranking.sort(key=lambda x: x["score"], reverse=True)
    return ranking
