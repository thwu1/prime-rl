The file `/app/cube_sim.py` implements a 3x3x3 Rubik's Cube facelet-level simulator using Kociemba facelet ordering (U0–U8, R0–R8, F0–F8, D0–D8, L0–L8, B0–B8; 54 facelets total, 6 center facelets fixed). The file `/app/scrambles.txt` contains 15 official WCA Fewest Moves Challenge scramble sequences in standard Singmaster notation.

Quality assurance has flagged the simulator as producing incorrect cube states. The nature and location of any defect has not been isolated — the basic move definitions, strip adjacency mappings, or both could be at fault. Running the simulator as-is (`python3 /app/cube_sim.py`) produces output to `/app/sim_output.json`, but these results should not be trusted.

Audit the simulator: identify the defective move definition and the specific nature of its error. Implement a correct simulator, then independently verify all permutation group properties using GAP (Groups, Algorithms, Programming — available at `/usr/bin/gap`).

Produce two output files:

**`/app/results.json`** with the following structure:

```json
{
  "scrambles": [
    {
      "index": 0,
      "facelet_string": "<54-char string in URFDLB face order>",
      "permutation_order": "<int: smallest k where scramble^k = identity>",
      "cycle_type": ["<sorted ascending list of cycle lengths over 48 non-center facelets>"],
      "num_fixed_facelets": "<int: non-center facelets unmoved by scramble>",
      "parity": "<even|odd>"
    }
  ],
  "diagnostics": {
    "buggy_move": "<single letter: U, R, F, D, L, or B>"
  },
  "gap_verified_orders": ["<list of 15 ints: permutation orders verified by GAP>"],
  "max_order_index": "<int: 0-based index of scramble with highest order>",
  "max_order": "<int: the highest permutation order>",
  "total_fixed": "<int: sum of num_fixed_facelets across all 15 scrambles>",
  "shared_cycle_type_pairs": ["<list of [i,j] pairs (i<j) with identical cycle types>"],
  "composite_order": "<int: order of the composition of all 15 scrambles applied sequentially>"
}
```

**`/app/gap_verify.g`** — the GAP script used for independent verification. It must define the six cube generators as permutations on the 48 non-center facelets, compose each scramble sequence, compute its order, and print results.

The solved cube facelet string is `UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB`. Centers (indices 4, 13, 22, 31, 40, 49) are excluded from cycle decomposition analysis.