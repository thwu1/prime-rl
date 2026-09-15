The text processing pipeline at `/app/transform.sh` reads from stdin and writes to stdout, chaining four GNU sed scripts—`/app/join.sed`, `/app/dedup.sed`, `/app/fold.sed`, and `/app/number.sed`—to perform sequential transformations. The pipeline is broken: existing scripts contain bugs, one script is unimplemented, and the pipeline itself has configuration errors. Fix all issues so the pipeline produces correct output for all test cases.

**Phase behavior** (in pipeline order):

1. **Join** (`join.sed`): Lines beginning with `> ` (greater-than, space) are continuations. Each continuation's content after the `> ` prefix appends to the preceding non-continuation line, separated by a single space. Multiple consecutive continuations join the same base line. A `> ` at the start of input with no predecessor is kept verbatim.

2. **Dedup** (`dedup.sed`): Consecutive identical lines collapse to one. Non-consecutive duplicates are preserved. Matching is exact and full-line—a prefix match is not a duplicate.

3. **Fold** (`fold.sed`): Consecutive lines sharing the same tag (everything before the first `:`) are folded into one line: the first line is kept intact, then each subsequent line's content after `<tag>:` (with leading spaces removed) is appended with ` | ` as separator. Lines without a colon pass through unchanged and break any active fold group. Single-entry tag groups pass through unchanged.

4. **Number** (`number.sed`): Every output line receives a `[NNN] ` prefix where `NNN` is a zero-padded 3-digit sequence number starting at `001`.

The pipeline must use **only** GNU sed—no awk, perl, python, tr, or other tools.

**Example**—given input:
```
Hello World
STATUS: booting
STATUS: ready
> and confirmed
STATUS: ready and confirmed
ERROR: disk full
ERROR: timeout
ERROR: timeout
Simple line
Last line
```

Correct output:
```
[001] Hello World
[002] STATUS: booting | ready and confirmed
[003] ERROR: disk full | timeout
[004] Simple line
[005] Last line
```

A sample input file is at `/app/sample_input.txt`.
