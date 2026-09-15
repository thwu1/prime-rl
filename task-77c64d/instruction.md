An environmental agency needs a comprehensive validation engine for EPA Water Quality Exchange (WQX) 3.0 XML data submissions. No pre-processed rule documentation is available — the engine must derive all validation constraints, discover applicable business rules, and reconstruct the schema's evolution history from the raw source materials provided.

## Available Materials

- `/app/schemas/` — WQX 3.0 XSD schema package (56 `.xsd` files; `root.xsd` is the entry point). Namespace: `http://www.exchangenetwork.net/schema/wqx/3`.
- `/app/domains/` — Controlled vocabulary reference CSVs for domain-constrained fields.
- `/app/change_log.txt` — Complete schema change history from v1.0 (2005) through v3.0 (2020), documenting element renames, field length expansions, cardinality changes, structural reorganizations, and schematron/business rule additions across all versions. Note: entries in earlier versions reference element names that were subsequently renamed.
- `/app/rules_summary.txt` — Brief natural-language descriptions of five conditional validation rules enforced by the WQX system. The exact element names, trigger conditions, and validation logic must be resolved from the schema and change log.
- `/app/submissions/` — Six XML submission files requiring conformance analysis.

Build `/app/wqx_engine.py` that processes all materials and produces the outputs below. No arguments required.

## Required Outputs

### `/app/type_system.json`

Resolved XSD type hierarchy derived from parsing all schema files. For each named `simpleType`, provide its resolved base primitive type (following `xs:restriction` chains through intermediate types) and all restriction facets. Include an element-to-type mapping for all globally declared elements.

```json
{
  "types": {
    "<TypeName>": {
      "base_type": "<xs:string|xs:integer|...>",
      "restrictions": {"maxLength": <int>, "minLength": <int>}
    }
  },
  "element_type_map": {
    "<ElementName>": "<TypeName>"
  }
}
```

### `/app/schema_evolution.json`

Structured analysis extracted from the schema change log:

```json
{
  "total_version_sections": <int>,
  "field_length_changes": [
    {"field": "<name>", "from_length": <int>, "to_length": <int>, "date": "<date_str>"}
  ],
  "element_renames": [
    {"old_name": "<str>", "new_name": "<str>", "date": "<date_str>"}
  ],
  "business_rules": [
    {"date": "<date_str>", "description": "<str>"}
  ]
}
```

### `/app/reports/<submission_filename>.json`

Per-file conformance report:

```json
{
  "file": "<filename>",
  "schema_valid": <bool>,
  "valid": <bool>,
  "total_errors": <int>,
  "violations": [{"category": "<str>", "element": "<str>", "detail": "<str>"}],
  "category_counts": {"<category>": <count>}
}
```

- `schema_valid`: structural validity against XSD schema package via `xmllint`
- `valid`: true only when `schema_valid` is true AND `total_errors` is 0
- Violation categories: `field_length`, `domain_value`, `business_rule`, `referential_integrity`
- `category_counts` tallies violations by their category

### Execution

```
python3 /app/wqx_engine.py
```