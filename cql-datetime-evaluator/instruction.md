Build a CQL (Clinical Quality Language) conformance test runner. The entry point is `bash /app/cql_runner.sh`.

The environment provides:

- `/app/test_suites/*.xml` — HL7 CQL conformance test suites (namespace `http://hl7.org/fhirpath/tests`, validated by `/app/testSchema.xsd`)
- `/app/testSchema.xsd` — XSD schema for the input test suite format
- `/app/reportSchema.xsd` — XSD schema defining the required output report format (namespace `http://hl7.org/fhirpath/tests/report`)

Required outputs:

`/app/input_validation.log` — Combined stdout+stderr of running `xmllint --schema /app/testSchema.xsd` against each test suite XML. Must contain "validates".

`/app/report.xml` — Conformance report that validates against `/app/reportSchema.xsd`. Each input test suite file maps to a `<suite>` element with `@source` set to the filename. Each test within a suite becomes a `<test-result>` with `@name`, `@group`, `@status`, and child elements `<expression>`, `<expected>`, `<computed>`. Status rules: `skip` if the test's `<expression>` element carries an `invalid` attribute; `pass` if the computed value matches the `<output>` text; `pass` if no `<output>` is present and evaluation succeeds without error; `error` on evaluation failure. The root element requires a `@generated` attribute (`xs:dateTime`). A `<summary>` element aggregates counts.

`/app/output_validation.log` — Combined stdout+stderr of running `xmllint --schema /app/reportSchema.xsd` against `/app/report.xml`. Must contain "validates".

The CQL expressions in the test suites cover temporal type constructors, date/time arithmetic, duration and difference calculations, precision-based timing comparisons, and standard comparison operators. The test suites define the expected evaluation semantics through their expressions and expected output values. Some tests have no `<output>` element — the runner must still evaluate these and report a computed value.

Success criteria: both validation logs confirm validity; all non-skipped tests produce correct computed values matching the expected outputs; the report validates against the report schema.
