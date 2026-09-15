"""Model ranking with configurable sort criteria.

The ranking configuration comes from /app/config.yaml and is passed
as a dict by pipeline/main.py. Implement rank_models to use this
config for dynamic sorting, rather than hardcoding sort criteria.
"""


def rank_models(model_results, ranking_config):
    """Rank models according to the provided ranking configuration.

    Args:
        model_results: list of model result dicts
        ranking_config: dict from config.yaml's 'ranking' section

    Returns:
        sorted list with 'rank' field added to each entry
    """
    raise NotImplementedError


def compute_unique_solves(evaluations, models):
    """Compute tasks uniquely solved by each model.

    A task is uniquely solved by a model if that model solved it
    (in at least one run) and no other model solved it.
    """
    raise NotImplementedError
