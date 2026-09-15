"""
Order Matcher - Solution Implementation

Multi-strategy fuzzy text matching for clinical order catalog lookup.
"""
from typing import Optional


class OrderMatcher:
    def __init__(self, catalog: list[dict]):
        self.entries = []
        for entry in catalog:
            matchable = [entry["canonical_name"].lower()]
            matchable.extend(a.lower() for a in entry.get("aliases", []))
            self.entries.append(
                {
                    "canonical_name": entry["canonical_name"],
                    "category": entry["category"],
                    "available_locations": entry.get("available_locations", []),
                    "matchable": matchable,
                    "processing_time_minutes": entry.get("processing_time_minutes", 0),
                }
            )

    @staticmethod
    def _levenshtein(s1: str, s2: str) -> int:
        """Compute Levenshtein edit distance between two strings."""
        if len(s1) < len(s2):
            return OrderMatcher._levenshtein(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (c1 != c2)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row
        return prev_row[-1]

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for token-based matching."""
        return text.replace("-", " ").replace("/", " ").lower()

    def _score_entry(self, query_lower: str, query_tokens: set, entry: dict) -> float:
        best_score = 0.0

        for target in entry["matchable"]:
            # Strategy 1: Exact match (case-insensitive)
            if query_lower == target:
                return 1.0

            # Strategy 2: Prefix match (min 3 chars)
            if len(query_lower) >= 3 and target.startswith(query_lower):
                score = 0.8 + 0.2 * (len(query_lower) / len(target))
                best_score = max(best_score, score)

            # Strategy 3: Token subset match
            target_normalized = self._normalize(target)
            target_tokens = set(target_normalized.split())
            if query_tokens and query_tokens.issubset(target_tokens):
                best_score = max(best_score, 0.7)

            # Strategy 4: Edit distance on individual words (min 3 char words)
            target_words = self._normalize(target).split()
            query_words = self._normalize(query_lower).split()
            for qw in query_words:
                if len(qw) < 3:
                    continue
                for tw in target_words:
                    if len(tw) < 3:
                        continue
                    dist = self._levenshtein(qw, tw)
                    if 0 < dist <= 2:
                        score = 0.5 - 0.1 * dist
                        best_score = max(best_score, score)

        return best_score

    def match(
        self, query: str, location: Optional[str] = None, top_k: int = 5
    ) -> list[dict]:
        query_lower = query.lower().strip()
        query_normalized = self._normalize(query_lower)
        query_tokens = set(query_normalized.split())

        results = []
        for entry in self.entries:
            if location and location not in entry["available_locations"]:
                continue

            score = self._score_entry(query_lower, query_tokens, entry)
            if score > 0:
                results.append(
                    {
                        "canonical_name": entry["canonical_name"],
                        "category": entry["category"],
                        "score": round(score, 4),
                    }
                )

        results.sort(key=lambda x: (-x["score"], x["canonical_name"]))
        return results[:top_k]
