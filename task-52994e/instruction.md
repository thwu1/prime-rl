`/app/scrambles.txt` contains five Rubik's Cube move sequences (one per line) in standard Singmaster notation: `R`, `R'`, `R2`, `U`, `U'`, `U2`, `F`, `F'`, `F2`, `D`, `D'`, `D2`, `L`, `L'`, `L2`, `B`, `B'`, `B2`. Moves within a sequence are space-separated and applied left-to-right starting from the solved cube.

Write a self-contained program (no external Rubik's Cube libraries such as `RubikTwoPhase`, `kociemba`, or `rubik`) that computes the following for each scramble and writes the results to `/app/results.json` as a JSON array of objects:

- `facelet_string` (string): 54-character cube definition string in Kociemba facelet order (U1–U9, R1–R9, F1–F9, D1–D9, L1–L9, B1–B9). Solved state: `UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB`.
- `twist` (int): Corner orientation coordinate, 0–2186. Base-3 encoding of the orientations of corners URF through DBL (first 7); the 8th (DRB) is determined by the mod-3 sum constraint. Orientations: 0 = untwisted, 1 = clockwise, 2 = counter-clockwise.
- `flip` (int): Edge orientation coordinate, 0–2047. Base-2 encoding of orientations of edges UR through BL (first 11); the 12th (BR) is determined by the mod-2 sum constraint.
- `corners` (int): Corner permutation coordinate, 0–40319. Factorial number system encoding computed via the rotate-left extraction method (Lehmer code variant used in the Kociemba two-phase solver).
- `order` (int): The order of the group element — smallest positive integer n such that applying the move sequence n times to a solved cube returns it to the solved state.

The cubie-level multiplication rule for composing states A and B at position x: `(A·B).perm[x] = A.perm[B.perm[x]]` and `(A·B).ori[x] = (A.ori[B.perm[x]] + B.ori[x]) mod m`, with m=3 for corners, m=2 for edges.