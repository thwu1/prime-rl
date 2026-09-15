# SQLLogicTest Format Reference

## Overview

The sqllogictest format defines SQL test cases with inline expected results for automated database conformance testing. Files use the `.test` extension. Each file contains a sequence of directives separated by blank lines. Lines starting with `#` are comments.

## Core Directives

### statement ok [@connection]
Execute SQL and expect success. SQL follows on subsequent lines until a blank line or `----`.

### statement error [@connection]
Execute SQL and expect failure. Optional `----` section contains expected error substring (case-sensitive).

### query \<types\> [sort_mode] [label] [@connection]
Execute a query and verify results after `----`.

- **types**: One character per column — `I` (integer), `T` (text), `R` (real). Length determines expected column count.
- **sort_mode**: `nosort` (default — compare in returned order), `rowsort` (sort rows lexicographically as tab-joined strings before comparing), `valuesort` (flatten all values across all columns into a single list, sort, compare one-per-line)
- **label**: Query group identifier for hash equivalence — all queries with the same label must produce identical result hashes
- **@connection**: Route execution to a named connection (any `@`-prefixed token)

Results after `----` are tab-separated rows. For `valuesort`, one value per line.

### loop \<var\> \<start\> \<end\> / endloop
Repeat body for `range(start, end)`. Substitute `${var}` in body. Supports nesting.

### foreach \<var\> \<val1\> \<val2\> ... / endforeach
Repeat body for each value. Substitute `${var}` in body. Supports nesting.

### require \<extension\>
Attempt to load the extension. Skip the **entire** test file if unavailable (exit 0, not failure).

### reconnect
Reset the connection pool while preserving the persistent database state.

### hash_threshold \<N\>
Auto-hash verification when a result exceeds N total scalar values.

### mode \<directive\>
Controls runner behavior. Supported directives: `verify`, `noverify`, `skip`, `unskip`. Study the test files for semantics.

## Value Representation

| Value | Representation |
|---|---|
| NULL | `NULL` |
| Empty string | `(empty)` |
| Boolean | `true` / `false` |
| Numbers | Standard string conversion |

## Hash Computation

Hash verification uses MD5. Values are collected in row-major order, converted to their string representation, joined with newlines, with a trailing newline appended, then hashed.

Format in expected results: `N values hashing to <md5hex>`

## Regex Matching

- `<REGEX>:pattern` — value must match the regex pattern
- `<!REGEX>:pattern` — value must NOT match the regex pattern

Uses DOTALL semantics. Applied per-value within tab-separated rows.

## Connection Model

Named connections (`@name`) are cursors created lazily from a shared database instance. All connections see the same persistent state. `reconnect` destroys all cursors; the database and its data persist.
