`/app/fast_bpe.py` contains a skeleton `FastBPETrainer` class with three methods to implement: `train()`, `encode()`, and `decode()`.

A correct but slow reference implementation is provided in `/app/naive_bpe.py` as `NaiveBPETrainer`. The naive version recomputes all pair statistics from scratch after every merge, making it prohibitively slow on larger corpora. Your `FastBPETrainer` must produce **identical** merge sequences (same pairs, same order) while completing 500 merges on `/app/data/corpus.txt` within 30 seconds.

Tie-breaking rule: when multiple pairs share the highest frequency, select the lexicographically smallest `(token1, token2)` tuple. The GPT-4 regex split pattern is used to prevent merges from crossing word/category boundaries. `encode()` and `decode()` must produce correct results using the trained merge table.

A training corpus is pre-generated at `/app/data/corpus.txt` (~600KB).