A Rubik's Cube analysis pipeline stores 12 cube states in a SQLite database at `/app/cubes.db` and ships with a validation microservice at `/app/validator/server.py` (HTTP on port 8888). The database uses a normalized schema — cube facelets, claimed generators, and claimed orders live in separate tables. QA suspects the validation service returns incorrect solvability assessments for certain inputs.

Audit every cube state. For each state, independently determine solvability, the specific violation type (if unsolvable), whether the claimed move generator is correct, and the group-theoretic order. Additionally, query the validation service for its assessment of each state and identify all discrepancies between the service's responses and your independent analysis.

## Data format

Facelet strings use 54 characters ordered U1–U9, R1–R9, F1–F9, D1–D9, L1–L9, B1–B9 (each face left-to-right, top-to-bottom). Solved state: `UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB`.

Move notation: U/R/F/D/L/B = 90° clockwise (viewing the face head-on), prime (') = counterclockwise, 2 = 180°. Moves are space-separated.

The group-theoretic order of a cube state is the smallest positive integer *k* such that applying the state's permutation *k* times yields the solved cube.

## Output format

`/app/report.json` — a JSON object keyed by state ID (C01–C12). Each entry:

```json
{
  "solvable": true,
  "violation": null,
  "generator_verified": true,
  "correct_order": 6,
  "service_response": {
    "solvable": true,
    "violation": null
  },
  "service_agrees": true
}
```

Fields:
- `solvable` (boolean): whether the facelet string represents a reachable cube configuration
- `violation` (string or null): for unreachable states, one of `"corner_orientation"`, `"edge_orientation"`, or `"permutation_parity"`; null for solvable states
- `generator_verified` (boolean or null): whether applying the claimed generator to the solved cube produces this exact facelet string; null for unsolvable states
- `correct_order` (integer or null): the true group-theoretic order; null for unsolvable states
- `service_response` (object): the exact JSON object returned by the validation service's `/validate/<facelet>` endpoint for this state
- `service_agrees` (boolean): whether the service's `solvable` field matches your independent `solvable` determination