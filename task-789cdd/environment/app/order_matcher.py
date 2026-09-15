"""
Order Matcher Module - CCS Clinical Simulation Engine

Implements fuzzy text matching to map free-text clinical orders to
canonical entries from the order catalog.

YOU MUST IMPLEMENT: The OrderMatcher class with the match() method.

Matching Strategy (implement all four, return max score per entry):

1. Exact match (case-insensitive) on canonical_name or any alias -> score 1.0

2. Prefix match: query (min 3 chars) is a prefix of canonical_name or alias
   (case-insensitive) -> score = 0.8 + 0.2 * (len(query) / len(target))

3. Token subset match: all whitespace-separated tokens in query appear in the
   target string (after normalizing hyphens/slashes to spaces) -> score 0.7

4. Edit distance match: Levenshtein distance <= 2 between any word in query
   and any word in target (skip words shorter than 3 chars) ->
   score = 0.5 - 0.1 * distance

Implementation notes:
- Levenshtein distance must be implemented from scratch (no external packages)
- All comparisons are case-insensitive
- Hyphens and slashes should be normalized to spaces for tokenization
- If location filter is provided, exclude entries not available at that location
- Return results sorted by score descending, limited to top_k
- Only return entries with score > 0
"""
from typing import Optional


class OrderMatcher:
    def __init__(self, catalog: list[dict]):
        """
        Initialize the OrderMatcher with an order catalog.

        Args:
            catalog: List of catalog entry dicts, each with keys:
                - canonical_name (str)
                - category (str)
                - aliases (list[str])
                - processing_time_minutes (int)
                - available_locations (list[str])
        """
        raise NotImplementedError("Implement OrderMatcher.__init__")

    def match(
        self, query: str, location: Optional[str] = None, top_k: int = 5
    ) -> list[dict]:
        """
        Match a free-text query to catalog entries.

        Args:
            query: Free-text order string (e.g., "ECG", "asprin", "chest xray")
            location: If provided, filter to entries available at this location
            top_k: Maximum number of results to return

        Returns:
            List of match result dicts sorted by score descending:
            [{"canonical_name": str, "category": str, "score": float}, ...]

            Only entries with score > 0 are included.
        """
        raise NotImplementedError("Implement OrderMatcher.match")
