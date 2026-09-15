# FileCheck Specification (Subset)

This document describes the correct semantics for a FileCheck-compatible pattern matching verifier. Use it as the authoritative reference when auditing the implementation.

## Directive Syntax

FileCheck directives appear in check files. A directive consists of a check prefix followed by an optional suffix and a colon, then a pattern:

    PREFIX(-SUFFIX)?: pattern

Directives may appear **anywhere on a line**, after any leading text. Common comment prefixes (`;`, `//`, `#`) often precede directives, but the tool must not require any specific leading character. The prefix itself is what identifies a directive — if the prefix text appears on the line followed by an optional suffix and a colon, it is a directive regardless of what precedes it.

## Directive Types

### CHECK: pattern
Scans forward in the input from the current position until a line matching `pattern` is found. Fails if no match is found before the end of input.

### CHECK-NEXT: pattern
Verifies that `pattern` matches on the **very next input line** after the previous match position. Fails if the immediately next line does not match. Does not scan forward.

### CHECK-SAME: pattern
Verifies that `pattern` matches on the **same line** as the previous match (the line just before the current position).

### CHECK-NOT: pattern
Verifies that `pattern` does **NOT** appear in the input between the previous positive match and the next positive match. The scan range is strictly bounded:
- The start of the range is the current input position (after the last positive match).
- The end of the range is the position where the **next** positive directive matches.
- If there is no subsequent positive directive, the range extends to the end of input.
- CHECK-NOT must NOT eagerly scan to end-of-file when a subsequent positive directive exists.

Implementation note: A correct implementation defers CHECK-NOT evaluation. When a CHECK-NOT is encountered, it is accumulated in a pending list. When the next positive directive (CHECK, CHECK-NEXT, CHECK-LABEL, CHECK-DAG, CHECK-COUNT) finds its match at position P, all pending CHECK-NOTs are verified in the range [current_position, P). Only then is the position advanced.

### CHECK-LABEL: pattern
Like CHECK, but resets the match context. Scans forward for a matching line.

### CHECK-DAG: pattern
A group of consecutive CHECK-DAG directives may match input lines in **any order**. Each pattern in the group must match a different input line within the available range. When patterns capture variables (`[[VAR:regex]]`), the matching engine **must** use backtracking to find a valid assignment of patterns to lines. A greedy first-fit approach is insufficient because an early assignment may capture a variable value that prevents a later pattern from matching, even though a different assignment would succeed. The engine must save and restore variable state when backtracking.

### CHECK-COUNT-\<N\>: pattern
Equivalent to one `CHECK: pattern` followed by N-1 `CHECK-NEXT: pattern` directives. The pattern must match on N **consecutive** input lines. The first match scans forward (like CHECK); subsequent matches require the immediately next line (like CHECK-NEXT). Fails if fewer than N consecutive matches exist.

## Pattern Syntax

- **Literal text**: matched exactly after regex-escaping. Case-sensitive by default.
- **`{{regex}}`**: inline regex — the content between `{{` and `}}` is used as a raw regex.
- **`[[VAR:regex]]`**: capture — matches `regex` and stores the matched text in variable `VAR`.
- **`[[VAR]]`**: substitution — replaced with the previously captured value of `VAR`. Fails if `VAR` is undefined.

## Multi-Prefix Mode

When `--check-prefixes=P1,P2,...` is specified, directives from **all** listed prefixes are collected from the check file. They are then **sorted by their line number** in the check file and processed in a **single unified matching pass**. The prefixes are NOT run as independent passes — interleaved directives from different prefixes must be processed in the order they appear in the check file.

`--check-prefix P` is equivalent to `--check-prefixes=P` (single prefix).

## CLI Options

- `--input-file FILE` — read input from FILE instead of stdin
- `--check-prefix PREFIX` — use PREFIX instead of the default `CHECK`
- `--check-prefixes P1,P2,...` — use multiple prefixes, merged by line order
- `--match-full-lines` — require positive patterns to match the entire input line (leading/trailing whitespace is ignored). CHECK-NOT patterns are not affected by this option. Implementation: wrap each positive pattern with `^\s*` ... `\s*$` anchors.
