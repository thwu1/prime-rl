The file `/app/ghenv.sh` is a shell implementation of the GitHub Actions environment file format processor. It handles files written to `$GITHUB_OUTPUT`, `$GITHUB_ENV`, and `$GITHUB_STATE` by workflow steps. The format specification is at `/app/spec.txt`.

The tool has multiple bugs across its parser and encoder, and its validator command is unimplemented. Fix all defects and implement missing functionality so the tool fully conforms to the specification.

## Commands

**`/app/ghenv.sh parse <file>`** — Parse the environment file and output a JSON array to stdout:
```json
[{"key": "name", "value": "content"}, ...]
```
String values must be properly JSON-escaped. Exit 0 on success, non-zero on error (message to stderr).

**`/app/ghenv.sh encode <json_file>`** — Read a JSON array of `{"key", "value"}` objects and write the equivalent environment file format to stdout. The encoder must produce output that round-trips correctly through the parser for arbitrary content, including content where lines match the heredoc delimiter string.

**`/app/ghenv.sh validate <file>`** — Check the file for all format errors without extracting values. Exit 0 if valid. Exit 1 if any errors found, printing each error to stderr in the format `line N: <description>`. Must report **all** errors in the file, not stop at the first.

**`/app/ghenv.sh roundtrip <json_file>`** — Encode the JSON input to file format, parse the result back, and verify the parsed output matches the original input. Print `PASS: Round-trip successful` (exit 0) on match, or `FAIL: Round-trip mismatch` (exit 1) on failure.

## Scope

The parser, encoder, validator, and round-trip commands must all conform to `/app/spec.txt`. Pay close attention to: the precedence rule when both `=` and `<<` appear on the same line, how heredoc values handle trailing newlines, empty-line behavior, how simple-format values containing `=` are split, heredoc delimiter safety in the encoder, and the four distinct error conditions listed in the spec.

Do not change the command-line interface or JSON schema. Sample input files are in `/app/testdata/`.
