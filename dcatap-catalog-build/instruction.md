An automated migration tool produced `/app/broken_catalog.ttl` by converting a DCAT-AP 2.x catalog to version 3.0.1, introducing numerous errors. The file `/app/manifest.json` describes the intended catalog contents, including the correct entity structure, metadata values, and the EU Publications Office authority table URI patterns that the catalog must use. All entities use the base URI `http://env-data.europa.eu/`.

The catalog contains 1 `dcat:Catalog`, 5 `dcat:Dataset` instances (DS001–DS005), 8 `dcat:Distribution` instances (DIST001–DIST008), at least 3 publishers, 1 `dcat:DataService`, and 1 `dcat:DatasetSeries`. The corrected output must preserve these exact entity counts.

Analyze the broken catalog against the DCAT-AP 3.0.1 specification and the manifest to identify all conformance violations, then produce the following four artifacts:

## `/app/catalog_fixed.ttl`

Corrected catalog in valid Turtle that fully conforms to DCAT-AP 3.0.1. Compare the broken catalog against the manifest and the DCAT-AP 3.0.1 specification to find and fix every violation.

## `/app/audit_report.json`

JSON array documenting every violation found. Must contain at least 12 entries spanning at least 4 distinct categories. Each entry must have exactly these fields: `{"error_id": "E<NNN>", "category": "<category>", "entity": "<affected URI>", "description": "<violation>", "fix": "<correction applied>"}`. Use categories from: `vocabulary_alignment`, `structural_modeling`, `property_usage`, `literal_correctness`, `cross_entity`.

## `/app/advanced_shapes.ttl`

Valid SHACL Turtle containing at least 5 `sh:NodeShape` resources, each with an `sh:targetClass`, enforcing cross-entity business rules:

1. Every `dcat:Dataset` must have a `dcat:contactPoint` typed as `vcard:Kind` with both `vcard:fn` and `vcard:hasEmail`.
2. CSV-format Distributions (those with `dct:format` pointing to the CSV file-type authority URI) must have `dcat:byteSize`.
3. Datasets linked via `dcat:inSeries` must have `dct:temporal` with a `dct:PeriodOfTime` containing both `dcat:startDate` and `dcat:endDate`.
4. Every Distribution must be referenced by at least one Dataset via `dcat:distribution` (no orphans).
5. CSV-format Distributions must have `dcat:mediaType`.

The corrected `catalog_fixed.ttl` must pass validation against these shapes (pyshacl, no inference). The shapes must also correctly reject non-conforming data: a Dataset without contactPoint, a series Dataset missing temporal endDate, and an orphan Distribution.

## `/app/validate.sh`

Executable bash script (must have execute permission) that validates `catalog_fixed.ttl` against `advanced_shapes.ttl` using pyshacl and reports conformance.