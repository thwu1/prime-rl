A naive Byte Pair Encoding (BPE) tokenizer trainer is provided at `/app/reference.py`. It rescans the entire token sequence to recompute pair statistics and apply replacements on every merge iteration, making training prohibitively slow on large corpora (O(N·M) where N is sequence length and M is the number of merges).

Implement `/app/fast_bpe.py` containing a `FastBPETrainer` class with method `train(text: str, num_merges: int) -> dict` that returns byte-identical results to the reference implementation while achieving substantially better asymptotic performance.

The return value is a `dict` mapping `(int, int)` pair tuples to integer token IDs starting at 256. The implementation must reproduce the reference's exact merge sequence: same pairs, same merge order, same tie-breaking semantics. Study `/app/reference.py` to understand what determines the tie-breaking behavior when multiple pairs share the highest frequency.

Test corpora of varying sizes are available at `/app/corpus_medium.txt` (~50 KB) and `/app/corpus_large.txt` (~640 KB). Precomputed reference merge tables are at `/app/reference_merges_medium.json` (500 merges) and `/app/reference_merges_large.json` (2000 merges).