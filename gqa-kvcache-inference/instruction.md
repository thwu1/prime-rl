A transformer model is provided at `/app/model.py`. It uses Grouped Query Attention (GQA) with 8 query heads and 2 key-value heads, Rotary Position Embeddings (RoPE), SwiGLU feed-forward layers, and RMSNorm. Its `generate_simple` function generates tokens autoregressively but recomputes the full forward pass over every token at each decoding step, making wall-clock time grow quadratically with output length.

## Part 1: Optimized Generation

Create `/app/kv_inference.py` that eliminates the redundant recomputation while producing **token-for-token identical** output to `generate_simple`. The module must export:

- **`KVCache`**: a class used internally by `generate_cached`
- **`generate_cached(model, input_ids, max_new_tokens)`**: returns a tensor of shape `(batch, prompt_len + max_new_tokens)` whose values are identical to `generate_simple(model, input_ids, max_new_tokens)`

You may modify `/app/model.py` if needed. Total sequence length (prompt + generated) will not exceed `context_length` (256).

## Part 2: Performance Profiling

Create `/app/profile_report.py`, executable via `python3 /app/profile_report.py` with no arguments. It must:

1. Produce Chrome trace-format JSON files at `/app/traces/baseline.json` and `/app/traces/optimized.json`, each capturing one invocation of the respective generation function with a prompt of at least 20 tokens and at least 30 generated tokens.
2. Write `/app/benchmark_results.json` containing at minimum `baseline_mean_ms`, `optimized_mean_ms`, and `speedup_ratio` (wall-clock milliseconds and their ratio), derived from repeated timing measurements (not a single run).