The file `/app/runner-env.sh` is a shell-based CI step environment state manager. It processes the GitHub Actions environment file format (`$GITHUB_OUTPUT`, `$GITHUB_ENV`) and provides persistent storage via SQLite, HMAC-based integrity verification, and concurrent-safe append operations. The script has multiple bugs spanning its parser, encoder, storage layer, integrity verifier, and locking mechanism. Fix all bugs so that every test passes.

## File Format Specification

Environment files store key-value pairs using two entry styles:

**Simple format:** `NAME=VALUE` — key is everything before the first `=`; value is everything after it.

**Heredoc format:**
```
NAME<<DELIMITER
value content
possibly spanning multiple lines
DELIMITER
```

Parsing rules:

- Empty lines are skipped
- When a line contains both `=` and `<<`, the token appearing at the lower character index determines the entry format
- In heredoc entries, the delimiter must appear alone on its own line as an exact match; the value is the content between the opening line and the delimiter line, excluding the newlines adjacent to both boundaries
- An unterminated heredoc must cause exit code 1 with an error to stderr
- An empty key or empty delimiter is an error
- Files that do not end with a trailing newline must be handled correctly

## Subcommands

`/app/runner-env.sh parse <file>` — JSON array `[{"key":"k","value":"v"}, ...]`. Return `[]` for empty/nonexistent files.

`/app/runner-env.sh encode <json-file> <output-file>` — Multi-line values use heredoc with collision-safe delimiters.

`/app/runner-env.sh validate <file>` — Exit 0 if valid; exit 1 with stderr message if invalid or missing.

`/app/runner-env.sh init <db-path>` — Create SQLite table: `outputs(step_id TEXT, key TEXT, value TEXT, hmac TEXT)`.

`/app/runner-env.sh store <db-path> <step-id> <env-file> <hmac-key>` — Parse env file, compute per-entry HMAC-SHA256 (hex) over `step_id:key:value` using the given key, insert all entries. Values with arbitrary characters (including single quotes and newlines) must be stored correctly.

`/app/runner-env.sh query <db-path> <step-id> [key]` — Return JSON array of matching `{"key","value"}` entries. Must handle values containing newlines.

`/app/runner-env.sh verify <db-path> <hmac-key>` — Recompute HMAC-SHA256 for every entry and compare against stored HMAC. Exit 0 if all match; exit 1 otherwise.

`/app/runner-env.sh append <lock-file> <env-file> <key> <value>` — Atomically append one entry using `flock`. Must block (not fail silently) when the lock is contended. Multi-line values use heredoc format with collision-safe delimiters.

## Correctness Requirements

- Round-trip fidelity: `parse(encode(data)) == data` for any valid input
- Values may contain `=`, `<<`, newlines, single quotes, `EOF`, any printable ASCII
- HMAC is SHA-256, computed over `step_id:key:value`, hex-encoded
- `append` must not silently drop entries under concurrent writes
