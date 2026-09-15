A Chevrotain-based schema parser at `/app/` is broken and incomplete. Fix all issues so it correctly lexes, parses, performs semantic validation, and outputs valid JSON.

The SDL syntax supports type declarations with typed fields and enum declarations:

```
type User { id: Int; name: String?; tags: [String]; }
enum Role { ADMIN, USER }
```

Field type modifiers: `Type` (required), `Type?` (nullable), `[Type]` (list). Line comments (`//`) are supported. Semicolons terminate fields; commas separate enum values.

Running `cd /app && npx tsx src/index.ts <file>` must exit 0 and write JSON to stdout:

```json
{
  "ast": {
    "types": [{"name":"User","fields":[{"name":"id","type":"Int","nullable":false,"list":false}]}],
    "enums": [{"name":"Role","values":["ADMIN","USER"]}]
  },
  "lexErrors": [],
  "parseErrors": [],
  "diagnostics": [{"severity":"error","message":"..."}]
}
```

The `diagnostics` array must contain semantic validation results:

- **Duplicate names**: two types/enums sharing the same name (case-sensitive exact match) produce an error whose message contains both the word "duplicate" and the conflicting name.
- **Undefined type references**: a field whose type is not defined in the schema and not a builtin (`Int`, `String`, `Boolean`, `Float`, `ID`) produces an error containing "undefined" and the missing type name.
- **Duplicate fields**: two fields with the same name within one type produce an error containing "duplicate" and the field name.
- **Duplicate enum values**: repeated values within one enum produce an error containing "duplicate" and the value.
- **Required reference cycles**: a cycle of types connected exclusively through non-nullable, non-list fields makes instantiation impossible. Both direct self-references and indirect multi-type cycles must be detected, each producing an error whose message contains "cycle" and the names of all participating types.

Error recovery: when a semicolon is missing after a field, the parser must recover via single-token insertion, report the error in `parseErrors`, and continue parsing subsequent fields.

Identifiers starting with keyword prefixes (e.g., `typeface`, `enumerate`) must lex as identifiers, not keywords.

Run `cd /app && npm install` before testing.

Files: `/app/src/tokens.ts`, `/app/src/parser.ts`, `/app/src/visitor.ts`, `/app/src/analyzer.ts`, `/app/src/index.ts`.
