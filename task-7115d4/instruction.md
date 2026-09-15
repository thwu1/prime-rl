The file `/app/spec.md` contains the specification for an esoteric functional programming language called ICFP (Interstellar Communication Functional Programs). The language features non-standard base-94 integer encoding, a custom string character mapping, lambda calculus with call-by-name evaluation, and capture-avoiding substitution.

The expression corpus is stored in a SQLite database at `/app/corpus.db`. The database contains multiple courses with expressions in different encoding formats. Only expressions belonging to active courses should be evaluated. Some expressions use a binary token encoding format; a C-language decoder source is provided at `/app/tools/` and must be compiled before use. The binary format documentation is in the database's `encoding_formats` table.

Evaluate all active expressions and write the results to `/app/results.json` as a JSON object mapping expression IDs to their evaluated values as strings:
- Integer results: decimal representation (e.g. `"1337"`)
- String results: the decoded human-readable string (e.g. `"Hello"`)
- Boolean results: `"true"` or `"false"`

Example format:
```json
{
  "expr_01": "1337",
  "expr_06": "Hello"
}
```

Some expressions cannot be evaluated within the 10,000,000 beta-reduction limit using naive call-by-name evaluation. Determining what these expressions compute and finding their results through alternative means is part of the challenge.