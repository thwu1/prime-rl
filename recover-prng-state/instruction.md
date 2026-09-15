Three stripped PRNG binaries at `/app/gen_alpha`, `/app/gen_beta`, and `/app/gen_gamma` each implement a different pseudo-random number generator algorithm. Three unlabeled output streams at `/app/stream_1.bin`, `/app/stream_2.bin`, and `/app/stream_3.bin` were each produced by exactly one of these generators (one-to-one mapping). Each stream contains 800 little-endian uint32 values (3200 bytes). The seeds are unknown and cannot be brute-forced. See `/app/notes.txt` for additional context.

Determine which generator produced each stream, recover internal state to predict future outputs, then conduct a quantitative security evaluation of all three generators and design an automated classifier that can identify which PRNG family produced an arbitrary output stream from structural analysis of the output alone.

Write these output files:

- `/app/matching.txt` — Three lines mapping streams to generators: `stream_N=gen_X` where X is `alpha`, `beta`, or `gamma` (each used exactly once).
- `/app/predictions_1.txt` — Next 5 outputs for stream 1 (positions 800-804), one hex value per line in `0x{value:08x}` format.
- `/app/predictions_2.txt` — Same format for stream 2.
- `/app/predictions_3.txt` — Same format for stream 3.
- `/app/weakest.txt` — Single line: the name of the generator (`gen_alpha`, `gen_beta`, or `gen_gamma`) most vulnerable to state recovery attacks.
- `/app/classifier.py` — Python script that takes a binary stream file path (800+ little-endian uint32 values) as its sole command-line argument and prints exactly one of `xorshift128`, `lcg64`, or `mt19937` to stdout, identifying the PRNG family. Must correctly classify streams generated with arbitrary seeds, not just the seeds in the provided streams.
- `/app/assessment.json` — Quantitative vulnerability assessment as JSON:
  ```
  {
    "generators": {
      "gen_alpha": {"algorithm": "...", "min_outputs_for_recovery": N, "attack_complexity": "O(...)"},
      "gen_beta": {"algorithm": "...", "min_outputs_for_recovery": N, "attack_complexity": "O(...)"},
      "gen_gamma": {"algorithm": "...", "min_outputs_for_recovery": N, "attack_complexity": "O(...)"}
    },
    "ranking_weakest_to_strongest": ["gen_...", "gen_...", "gen_..."]
  }
  ```
  Each generator entry must specify the identified algorithm name, the minimum number of consecutive outputs required to recover full internal state, and the computational complexity of the state recovery attack. The ranking array lists all three generators ordered from most to least vulnerable.