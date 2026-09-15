```
```

fzf is a command-line fuzzy finder installed at `/usr/local/bin/fzf`. Its matching engine uses several distinct algorithms internally, each producing `(start_index, end_index, score)` tuples that determine how results are filtered and ranked. The scoring system accounts for character boundaries, case transitions, delimiter positions, consecutive matches, gap penalties, and more — all interacting in non-obvious ways.

Build a Python module at `/app/fzf_match.py` that exactly replicates the matching behavior of fzf's five core match functions under the **default** scoring scheme (`--scheme=default`). The module must expose:

```python
def fuzzy_match_v2(text: str, pattern: str, case_sensitive: bool = False) -> tuple[int, int, int]:
    """Optimal fuzzy match. Returns (start, end, score) or (-1, -1, 0)."""

def exact_match_naive(text: str, pattern: str, case_sensitive: bool = False) -> tuple[int, int, int]:
    """Contiguous substring match at highest-scoring position. Returns (start, end, score) or (-1, -1, 0)."""

def prefix_match(text: str, pattern: str, case_sensitive: bool = False) -> tuple[int, int, int]:
    """Prefix match (strips leading whitespace). Returns (start, end, score) or (-1, -1, 0)."""

def suffix_match(text: str, pattern: str, case_sensitive: bool = False) -> tuple[int, int, int]:
    """Suffix match (strips trailing whitespace). Returns (start, end, score) or (-1, -1, 0)."""

def equal_match(text: str, pattern: str, case_sensitive: bool = False) -> tuple[int, int, int]:
    """Exact whole-string match (strips surrounding whitespace). Returns (start, end, score) or (-1, -1, 0)."""
```

Each function must produce exact `(start, end, score)` agreement with fzf's corresponding internal implementation. All five match types share the same underlying scoring infrastructure — character classification, position-dependent bonuses, and gap penalties — but differ in how they locate the match region within the text.

The implementation will be validated against test vectors derived from fzf's own test suite, requiring exact numeric score agreement across all five match types. Test cases cover camelCase boundaries, delimiter boundaries, whitespace boundaries, consecutive match propagation, gap penalties, case sensitivity modes, empty patterns, and non-match cases.

You have access to the fzf binary for probing behavior and internet access for consulting fzf's source code.