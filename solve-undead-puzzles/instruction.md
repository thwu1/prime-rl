Seven Undead puzzle instances are stored in `/app/puzzles.bin`, a custom binary container where each puzzle's data block is XOR-encrypted with a per-puzzle key derived from a 16-byte seed in the file header. A stripped validator binary at `/app/undead-check` accepts or rejects solutions via exit code (0=valid, 1=invalid, 2=error) with no informative output; its format-revealing strings are obfuscated. `/app/meta.db` (SQLite) contains per-puzzle dimensions, total monster counts, and clue checksums (first 16 hex chars of SHA-256 over comma-joined clue values in `top,bottom,left,right` order). `/app/src/undead_rules.c` documents the sight-line visibility algorithm.

Each puzzle is an NxN grid containing diagonal mirrors (`/` and `\`). Every non-mirror cell must be filled with exactly one monster: Vampire (`V`), Ghost (`G`), or Zombie (`Z`). Numeric clues along each grid edge specify how many monsters are visible along each sight line entering from that edge. Visibility depends on mirror reflections: Vampires are visible only before the first mirror reflection, Ghosts only after at least one reflection, and Zombies regardless of reflection state.

Reverse-engineer the encrypted binary container format and the per-puzzle key derivation scheme, decrypt and extract all puzzle constraints, solve all seven puzzles, and write valid solutions to `/app/solutions/solution_1.txt` through `/app/solutions/solution_7.txt` that pass `/app/undead-check`.

## Solution File Schema

Each solution file `/app/solutions/solution_<id>.txt` **must** conform to this specification:

**Structure:**

```
<header_line>
<grid_row_1>
<grid_row_2>
...
<grid_row_N>
```

**Field definitions:**

| Field | Line(s) | Format | Description |
|-------|---------|--------|-------------|
| Header | 1 | `UNDEAD v1 <id>` | Literal prefix `UNDEAD v1 ` followed by puzzle ID as decimal integer (1-7). |
| Grid | 2 to N+1 | N characters per line | One row of the NxN grid per line, no separators between characters. |

**Grid character set:**

| Character | Meaning |
|-----------|---------|
| `V` | Vampire |
| `G` | Ghost |
| `Z` | Zombie |
| `/` | Forward-slash mirror |
| `\` | Backslash mirror |

**Constraints:**

- Grid dimension N must match the puzzle's specification (available in `/app/meta.db` field `dim`).
- Mirror characters must appear at exactly the positions specified in the puzzle data.
- Total counts of each monster type (V, G, Z) must match the puzzle's specification.
- All 4N edge sight-line visibility clue values must be satisfied.
- No trailing whitespace on any line. No blank lines after the grid. File ends with a newline after the last grid row.