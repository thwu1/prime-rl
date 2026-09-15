A partial Python port of fzf's fuzzy matching engine exists at `/app/fzf_scorer.py`. The scoring constants, character classification, and bonus matrix are already implemented. The core matching functions are unimplemented stubs that raise `NotImplementedError`.

Complete all unimplemented functions so that the module produces bit-exact results — identical start index, end index, and score — matching fzf's matching behavior for all supported match types: `fuzzy_match_v1`, `fuzzy_match_v2`, `exact_match_naive`, `prefix_match`, `suffix_match`, `equal_match`, plus their helpers `normalize_rune`, `try_skip`, `ascii_fuzzy_index`, and `calculate_score`.

Reference materials available in the environment:

- fzf's authoritative Go implementation: `/app/fzf-src/src/algo.go`
- fzf's Go test vectors: `/app/fzf-src/src/algo_test.go`
- fzf binary installed at `/usr/bin/fzf`

Write your completed implementation to `/app/fzf_scorer.py`. The module must expose all functions defined in the scaffold with identical signatures.