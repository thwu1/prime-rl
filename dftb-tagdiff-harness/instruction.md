The directory `/app/` contains `tagdiff.sh` and `harness.sh` — shell tools for comparing tagged scientific output files against golden references using configurable numeric tolerances. Both have multiple bugs producing incorrect comparison results, wrong exit codes, and missing outputs.

Debug and fix both scripts so they pass the full verification suite.

## tagdiff.sh

**`/app/tagdiff.sh [-c configfile]... ref_file new_file`**

Reads tolerance rules from config files (`-c` flags; default: `tagdiff.conf` beside the script). Compares entries in `ref_file` against `new_file`. Exits 0 when no verdict is `Failed` or `Error`; non-zero otherwise. Non-zero exit also when any input file is missing. Input files (tag and config) ending in `.gz` must be transparently decompressed.

**Output**: one line per matched entry, four columns: name, method (`element` or `vector:N`), difference or message, verdict (`OK`|`Failed`|`Skipped`|`Error`). Each reference entry produces at most one line unless `keep` is set.

**Config fields** (separated by `@`):

1. Regex pattern matched against entry tag `name:type:rank:shape`
2. Absolute tolerance (`atol`)
3. Method: `element` | `vector:N` (default: `element`)
4. `keep` | `nokeep` (default: `nokeep`); OR `rtol:VALUE` when keep/nokeep is omitted
5. `rtol:VALUE` — relative tolerance (optional; present here when field 4 is keep/nokeep)

Rules from earlier `-c` files take priority; within each file, rule order matters.

**Tolerance**: passes when `diff <= max(atol, rtol * magnitude)` where `magnitude` = maximum absolute value among the reference entry's numeric values. Without `rtol`, only `atol` applies. When magnitude is zero, only `atol` applies.

**Element method**: max absolute element-wise difference. **Vector method** (`vector:N`): Euclidean norm per N-element block, max across blocks.

**Types**: `real`/`integer` — numeric comparison. `complex` — interleaved real/imaginary pairs, modulus `sqrt(dre^2 + dim^2)` per pair. `logical` — `T`/`t` maps to 1, `F`/`f` maps to 0, then numeric.

**Consumption**: `nokeep` (default) removes the entry after processing so later rules cannot rematch it. `keep` leaves the entry available for subsequent rules.

**Verdicts**: `OK` (within tolerance), `Failed` (exceeds), `Skipped` (not in new file — not a failure), `Error` (type/rank/shape/count mismatch).

## harness.sh

**`/app/harness.sh`**

Iterates directories under `/app/testcases/*/` in sorted order. Each has `_autotest.tag` and `autotest.tag`. When a directory has its own `tagdiff.conf`, load it before the global `/app/tagdiff.conf` via `-c` flags. Write:

- `/app/results.json`: `{"passed": N, "failed": N, "total": N}` (integers, `total == passed + failed`)
- `/app/detail.log`: one line per test case, alphabetically: `<name> PASS` or `<name> FAIL`

Exit 0 only when all cases pass.

## Constraints

- Use bash and gawk (installed); do not modify `/app/testcases/`, `/app/tagdiff.conf`, or `/app/lib/`
