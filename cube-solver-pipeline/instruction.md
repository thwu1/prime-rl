You have 5 official WCA scramble sequences in `/app/scrambles.json` (JSON array of strings in standard Singmaster notation), a dataset of FMC competition results in `/app/fmc_results.tsv`, and 5 deliberately corrupted cube states in `/app/invalid_states.json`.

The 54-character facelet string uses URFDLB face order (9 facelets per face, read left-to-right top-to-bottom when viewed from outside). Solved state: `UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB`. Cubie numbering conventions are defined in `/app/cubie_conventions.json`.

Produce the following output files in `/app/output/`:

**`cubie_decomposition.json`** -- JSON array of 5 objects. For each scramble, decompose the scrambled cube state into cubie-level coordinates following the conventions in `/app/cubie_conventions.json`. Each object must have:
- `corner_permutation`: array of 8 ints -- `perm[i]` is the ID of the corner cubie occupying position `i`
- `corner_orientation`: array of 8 ints -- twist (0, 1, or 2) of the corner cubie at each position
- `edge_permutation`: array of 12 ints -- `perm[i]` is the ID of the edge cubie occupying position `i`
- `edge_orientation`: array of 12 ints -- flip (0 or 1) of the edge cubie at each position

**`algebraic_orders.json`** -- JSON array of 5 objects. For each scramble, compute the permutation order using the algebraic cycle structure of the cubie-level representation (NOT brute-force iteration). Each object must have:
- `corner_cycle_type`: sorted list of cycle lengths in the corner permutation
- `edge_cycle_type`: sorted list of cycle lengths in the edge permutation
- `augmented_corner_orders`: sorted list of augmented orders per corner cycle (accounting for orientation within the wreath product)
- `augmented_edge_orders`: sorted list of augmented orders per edge cycle (accounting for flip within the wreath product)
- `permutation_order`: int, the LCM of all augmented cycle orders

**`solvability_analysis.json`** -- JSON array of 5 objects. For each corrupted state in `/app/invalid_states.json`, perform full cubie decomposition and check the three solvability invariants of the Rubik's cube group. Each object must have:
- `corner_twist_sum_mod3`: int (0, 1, or 2)
- `edge_flip_sum_mod2`: int (0 or 1)
- `corner_parity`: int (0 for even, 1 for odd)
- `edge_parity`: int (0 for even, 1 for odd)
- `violations`: list of strings from `["corner_twist", "edge_flip", "parity_mismatch"]`
- `solvable`: boolean

**`solutions.json`** -- JSON array of 5 objects, each with `"solution"` (move string restoring the solved state), `"move_count"` (integer, must be <= 25), and `"verified"` (boolean, must be `true`).

**`statistics.json`** -- JSON object with keys:
- `"sub20_count"`: number of unique `person_id` values with at least one positive `best` <= 20
- `"largest_competition"`: `competition_id` with the most unique `person_id` values
- `"most_results_person"`: `person_id` with the most rows where `best` > 0

TSV columns: `id`, `pos`, `best`, `average`, `competition_id`, `round_type_id`, `event_id`, `person_name`, `person_id`, `format_id`, `regional_single_record`, `regional_average_record`, `person_country_id`.