The environment contains:

- `/app/bpe_encoder` — a stripped ELF binary that reads `/app/model.bin` and performs greedy BPE encoding (subcommands: `encode <text>`, `decode <id>...`, `info`). No source code is provided.
- `/app/model.bin` — BPE merge table in an undocumented packed binary format. The format uses a variable-offset header layout — merge data does not start at a fixed file position.
- `/app/buggy_tokenizer.py` — a reference implementation that only loads minbpe text-format models (incompatible with `model.bin`). Its greedy encoding is provably suboptimal for certain inputs.
- `/app/test_vectors.json` — encoding statistics showing that certain inputs can be encoded with fewer tokens than greedy BPE produces.

Reverse-engineer the compiled binary's model-loading behavior using system-call tracing and binary analysis to determine the format's header structure, field sizes/endianness, and the offset to the merge data section. Build a Python tokenizer that matches the binary's greedy encoding and surpasses it with optimal (minimum-token-count) encoding. Export the reconstructed merge table and encoding comparisons to a SQLite database.

## Deliverables

### `/app/tokenizer.py` — `BPETokenizer` class

**Attribute:** `vocab: dict[int, bytes]` — token ID to byte sequence (0–255 are single bytes; merged tokens start at 256, numbered by merge rank).

**Methods:**
- `load(model_path)` — parse the binary model and populate `vocab` and merge structures
- `decode(ids) -> str` — concatenate token byte sequences and decode as UTF-8
- `greedy_encode(text) -> list[int]` — standard greedy BPE (must produce identical output to `bpe_encoder encode`)
- `optimal_encode(text) -> list[int]` — minimum-token-count encoding over the full vocabulary; `decode(optimal_encode(t)) == t` and `len(optimal_encode(t)) <= len(greedy_encode(t))` for all inputs; must handle ~10 KB within 30 seconds
- `compression_gap(text) -> int` — `len(greedy_encode(text)) - len(optimal_encode(text))`
- `count_optimal_tokenizations(text) -> int` — number of distinct minimum-length token-ID sequences that decode to the original input (1 for empty input)

### `/app/tokenizer.db` — SQLite database

**Table `merges`:** `rank INTEGER PRIMARY KEY, parent0 INTEGER, parent1 INTEGER, merged_id INTEGER, merged_bytes_hex TEXT`
- All merges from the model. `merged_bytes_hex` is the hex encoding of the merged token's byte sequence (e.g. `"6520"` for bytes `[101, 32]`).

**Table `encodings`:** `input_text TEXT PRIMARY KEY, greedy_ids TEXT, greedy_count INTEGER, optimal_ids TEXT, optimal_count INTEGER, gap INTEGER`
- One row per test vector that has both `reference_tokens` and `min_tokens` fields in `/app/test_vectors.json`. `greedy_ids` and `optimal_ids` are JSON arrays of token IDs. `gap` is `greedy_count - optimal_count`.