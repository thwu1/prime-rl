#!/usr/bin/env python3
"""BGP Best-Path Selection Engine

Implement the BGP best-path selection algorithm.
See /app/SPEC.md for the complete algorithm specification.
See /app/scenarios.json for test scenarios with expected outputs.

Your implementation must provide:
- select_best_path(scenario: dict) -> int
  Takes a scenario dict with 'config' and 'routes' keys.
  Returns the 0-based index of the best path in the routes list,
  or -1 if no valid paths exist.
"""



def select_best_path(scenario: dict) -> int:
    """Select the best BGP path from candidate routes.

    Args:
        scenario: dict with keys:
            - config: dict with boolean configuration flags
            - routes: list of route dicts with BGP path attributes

    Returns:
        0-based index of best path in routes list, or -1 if no valid paths
    """
    raise NotImplementedError("Implement the BGP best-path selection algorithm")
