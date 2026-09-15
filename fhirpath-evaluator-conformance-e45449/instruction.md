Implement a FHIRPath expression evaluator in JavaScript (Node.js) that passes a curated subset of the official HL7 FHIRPath conformance test suite.

The test suite XML is at `/data/tests-fhir-r4.xml`. FHIR resource files are in `/data/resources/` (`patient-example.xml`, `observation-example.xml`). The FHIRPath ANTLR grammar is at `/data/FHIRPath.g4` for reference.

Create `/app/evaluate.js` — a CLI that accepts a resource file path and a FHIRPath expression, evaluates the expression against the resource, and prints a JSON result to stdout:

```
node /app/evaluate.js <resource_path> '<fhirpath_expression>'
```

**Output format** (JSON on stdout):
- Successful evaluation: `{"results": [{"type": "boolean", "value": "true"}, {"type": "string", "value": "Peter"}]}`
- Empty collection result: `{"results": []}`
- Invalid expression or runtime error: `{"error": "syntax|semantic|execution"}`

Type strings in results must match the test suite types: `boolean`, `integer`, `decimal`, `string`, `date`, `dateTime`, `time`, `code`, `Quantity`.

**Required conformance test groups** (all tests in each group must pass):

| Group | Count | Core challenge |
|---|---|---|
| `testEquality` | 28 | `=` with date precision propagation, timezone normalization, quantity unit matching, ordered collection comparison |
| `testNEquality` | 24 | `!=` including `round()` and quantity unit awareness |
| `testEquivalent` | 24 | `~` with case-insensitive strings, significance-based decimal comparison, unordered collection equivalence |
| `testNotEquivalent` | 22 | `!~` |
| `testBooleanLogicAnd` | 9 | Three-valued `and` with empty collection propagation |
| `testBooleanLogicOr` | 9 | Three-valued `or` |
| `testBooleanLogicXOr` | 9 | Three-valued `xor` |
| `testBooleanImplies` | 9 | Three-valued `implies` |
| `testQuantity` | 8 | Quantity unit conversion (g/mg/kg, days/weeks) for tests 1-8 |

**Key semantic requirements:**
- Comparing dates/times at different precision levels returns empty (not false), e.g. `@2012-04-15 = @2012-04-15T10:00:00` yields `{}`.
- DateTimes with timezone offsets must be normalized before comparison: `@2012-04-15T15:00:00+02:00 = @2012-04-15T16:00:00+03:00` is `true`.
- Equivalence (`~`) for strings is case-insensitive; for collections is order-independent; for decimals uses significance-based rounding.
- Boolean operators propagate empty collections per FHIRPath three-valued logic tables (e.g., `false and {} = false`, `true or {} = true`, `false implies {} = true`).
- Quantity comparison requires converting between compatible UCUM units (grams/milligrams, days/weeks).
- FHIR XML resources use `value` attributes for primitives and polymorphic `value[x]` elements (e.g., `valueQuantity`).

**Supporting functions required by the test expressions:** `empty()`, `not()`, `count()`, `first()`, `last()`, `take(n)`, `skip(n)`, `exists()`, `round(n)`, `is(Type)`, `select()`, `given` (path navigation), union operator `|`, arithmetic (`+`, `-`, `*`, `/`), parenthesized expressions, and all literal types (integer, decimal, string, boolean, date, dateTime, time, quantity, empty `{}`).
