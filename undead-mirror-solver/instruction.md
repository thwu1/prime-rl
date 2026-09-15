Build a system that generates Undead (Haunted Mirror Maze) puzzle instances, each with a provably unique solution. Write 6 puzzles to `/app/generated/`.

## Puzzle Specifications

| Puzzle     | Grid | Mirror count |
|------------|------|-------------|
| puzzle_01  | 5×5  | 2–5         |
| puzzle_02  | 5×5  | 8–12        |
| puzzle_03  | 7×7  | 4–9         |
| puzzle_04  | 7×7  | 16–22       |
| puzzle_05  | 9×9  | 6–14        |
| puzzle_06  | 9×9  | 28–36       |

Each puzzle must satisfy **all** of the following:

- **Unique solution**: exactly one assignment of monsters to empty cells satisfies all constraints simultaneously. No alternative valid assignment may exist.
- **All monster types present**: Ghost, Vampire, and Zombie counts each ≥ 1.
- **Non-degenerate clues**: at least one non-zero edge clue on each of the four sides (top, bottom, left, right).

## Puzzle Rules

The grid contains mirrors (`\` and `/`) at fixed positions and empty cells. Each empty cell must hold exactly one monster type: Ghost (`G`), Vampire (`V`), or Zombie (`Z`). The puzzle specifies the required total count of each type.

Numbered clues along each grid edge state how many monsters are visible along the corresponding line of sight. A sight line enters the grid perpendicular to the edge and traverses cells sequentially. Mirrors deflect rays: `\` swaps the row and column components of the direction vector; `/` swaps and negates them. Whether a monster counts as visible depends on its type and the ray's current reflection state:

- **Zombie** — always visible regardless of reflections
- **Ghost** — visible only before any reflection (direct line of sight)
- **Vampire** — visible only after at least one reflection (seen in a mirror)

A valid solution fills every empty cell with a monster such that all edge clue counts and all monster type totals are simultaneously satisfied.

## `.desc` Format

Each puzzle file is a single line: `WxH:c1,c2,...,gcount,vcount,zcount,grid_rle`

- `WxH` — grid width × height
- Next `2*(W+H)` comma-separated integers — edge clues ordered: top (left→right), bottom (left→right), left (top→bottom), right (top→bottom)
- `gcount,vcount,zcount` — required Ghost, Vampire, Zombie totals
- `grid_rle` — row-major grid encoding: lowercase letter `a`–`z` encodes 1–26 consecutive empty cells; `L` encodes a `\` mirror; `R` encodes a `/` mirror

## Output

For each puzzle XX (01 through 06), write two files:

- `/app/generated/puzzle_XX.desc` — puzzle description in `.desc` format
- `/app/generated/puzzle_XX.json` — solution as `{"grid": [["G", "\\", "V", "Z"], ...]}`

The grid is a row-major 2D array. Mirror cells contain `"/"` or `"\\"`. Monster cells contain `"G"`, `"V"`, or `"Z"`.