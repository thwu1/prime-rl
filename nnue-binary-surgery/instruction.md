The Stockfish chess engine embeds a neural network (NNUE) for position evaluation, stored in a proprietary binary format. A pre-built Stockfish binary is at `/app/stockfish`. The complete source repository is at `/app/Stockfish/`. The default NNUE network file is somewhere in `/app/` (you will need to determine its exact filename).

Your task has two parts:

**Part 1 — Binary Analysis.** Write `/app/nnue_parser.py` that parses the NNUE binary file and produces `/app/analysis.json` with the following fields:

- `description` — the network description string extracted from the binary file header
- `hash` — the header hash value as a hex string (format: `"0xABCD1234"`)
- `version` — the header version number (integer)
- `ft_output_dim` — feature transformer output dimensionality
- `ft_bias_count` — number of feature transformer bias parameters
- `ft_bias_sum` — integer sum of all feature transformer bias values (as stored in the file, before any modification)
- `layer_stacks` — number of network layer stacks
- `psqt_buckets` — number of PSQT buckets

**Part 2 — Binary Surgery.** Produce `/app/modified.nnue` — a modified copy of the network where every feature transformer bias has been increased by 10, properly re-encoded in the same binary format. This file must:

- Load successfully in Stockfish via `setoption name EvalFile value /app/modified.nnue`
- Produce different position evaluations than the original network

The binary format is not publicly documented outside of the C++ source code under `/app/Stockfish/src/`. You will need to reverse-engineer the format by studying the source.