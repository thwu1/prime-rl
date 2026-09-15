`/app/grammars/` contains the official HL7 Clinical Quality Language (CQL) v1.5 ANTLR4 grammar files (`cql.g4` and `fhirpath.g4`). `/app/fixtures/` contains XML conformance test fixtures from the CQL test suite — each file has groups of tests pairing a CQL `<expression>` with an expected `<output>`.

Produce `/app/cql_runner.py`: a CLI that evaluates CQL expressions from the fixture files using an ANTLR4-generated parser.

**Parser**: Generate Python3 parser/lexer files into `/app/generated/` from the provided grammars (adapting them as needed for standalone expression parsing). At least one file matching `*Lexer.py` and one matching `*Parser.py` must exist there, and must be genuine ANTLR4-generated code (containing `antlr4` imports).

**Single-file mode**: `python3 /app/cql_runner.py <path.xml>` processes one fixture file and writes JSON to stdout:

```json
{"file":"<basename>","tests":[{"name":"<test-name>","group":"<group-name>","expression":"...","expected":"...","actual":"...","pass":true}],"summary":{"total":N,"passed":N,"failed":N}}
```

Each test object must include all six keys. `summary.total` must equal `summary.passed + summary.failed`.

**Batch mode**: `python3 /app/cql_runner.py --batch` processes every `.xml` in `/app/fixtures/` and outputs a JSON array of the above objects (one per file).

**Exclusions**: Tests whose `<expression>` element carries an `invalid` attribute (any value) must be omitted from output entirely.

**ANTLR4 toolchain**: The `antlr4-python3-runtime` package must be installed. The generated parser must contain a `serializedATN` field (characteristic of ANTLR4 code generation).

**Pass rate**: The runner must achieve ≥85% pass rate (`total passed / total tests`) across all fixtures combined when run in batch mode.
