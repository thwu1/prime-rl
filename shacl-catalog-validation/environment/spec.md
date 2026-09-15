# SciDCAT-Env Application Profile Specification v1.0

## Overview

SciDCAT-Env is an application profile that extends DCAT-AP 3.0.1 with additional mandatory constraints for environmental scientific datasets. It targets catalogs aggregating geospatial environmental monitoring data from EU research and reporting programs.

All standard DCAT-AP 3.0.1 mandatory properties remain required:
- **dcat:Catalog**: `dct:title`, `dct:description`, `dct:publisher` (pointing to a `foaf:Agent`)
- **dcat:Dataset**: `dct:title`, `dct:description`
- **dcat:Distribution**: `dcat:accessURL`
- **foaf:Agent**: `foaf:name`

The constraints below are **additional** requirements imposed by this profile.

## RDF Namespaces

| Prefix | URI |
|--------|-----|
| dcat   | http://www.w3.org/ns/dcat# |
| dct    | http://purl.org/dc/terms/ |
| foaf   | http://xmlns.com/foaf/0.1/ |
| locn   | http://www.w3.org/ns/locn# |
| spdx   | http://spdx.org/rdf/terms# |
| skos   | http://www.w3.org/2004/02/skos/core# |
| xsd    | http://www.w3.org/2001/XMLSchema# |
| geo    | http://www.opengis.net/ont/geosparql# |
| sh     | http://www.w3.org/ns/shacl# |

## Constraints on dcat:Dataset

| Property | Cardinality | Range / Datatype | Notes |
|----------|-------------|------------------|-------|
| `dct:spatial` | 1..* | `dct:Location` (node) | Each Location node **MUST** have both `locn:geometry` (a WKT literal typed as `geo:wktLiteral`) **AND** `locn:geographicName` (a plain or language-tagged string literal). Model this as a nested `sh:NodeShape` referenced via `sh:node`. |
| `dct:temporal` | 1..* | `dct:PeriodOfTime` (node) | Each PeriodOfTime node **MUST** have exactly one `dcat:startDate` (typed `xsd:date`) **AND** exactly one `dcat:endDate` (typed `xsd:date`). Model as a nested `sh:NodeShape`. |
| `dcat:keyword` | 3..* | `rdfs:Literal` | At least three keyword values per dataset. |
| `dcat:theme` | 1..* | `skos:Concept` | Must reference instances typed as `skos:Concept`. Use `sh:class skos:Concept`. |
| `dct:accrualPeriodicity` | 1..1 | — | Exactly one update frequency URI. |
| `dcat:spatialResolutionInMeters` | 1..1 | `xsd:decimal` | Typed as `xsd:decimal`. Enforce with `sh:datatype`. |
| `dct:conformsTo` | 1..1 | — | Reference to the data specification or reporting standard. |
| `dct:creator` | 1..* | `foaf:Agent` | At least one creator agent. |

## Constraints on dcat:Distribution

| Property | Cardinality | Range / Datatype | Notes |
|----------|-------------|------------------|-------|
| `dcat:mediaType` | 1..1 | — | IANA media type reference (as IRI). |
| `dct:format` | 1..1 | — | EU Publications Office file type (as IRI). |
| `dcat:byteSize` | 1..1 | — | File size value. |
| `spdx:checksum` | 1..1 | `spdx:Checksum` (node) | Checksum node **MUST** have exactly one `spdx:checksumValue` **AND** exactly one `spdx:algorithm`. Model as a nested `sh:NodeShape`. |

## Constraints on dcat:Catalog

| Property | Cardinality | Range / Datatype | Notes |
|----------|-------------|------------------|-------|
| `dct:spatial` | 1..* | — | Geographic area covered by the catalog. |
| `dcat:themeTaxonomy` | 1..* | — | Theme classification scheme used by the catalog. |
| `dct:license` | 1..1 | — | License governing catalog reuse. |

## Constraints on foaf:Agent

| Property | Cardinality | Range / Datatype | Notes |
|----------|-------------|------------------|-------|
| `foaf:mbox` | 1..1 | — | Contact email as a `mailto:` URI (per FOAF convention). |

## Shape Implementation Requirements

- SHACL shapes **MUST** use `sh:NodeShape` with `sh:targetClass` for each constrained class above.
- Nested entity constraints (Location geometry+name, PeriodOfTime dates, Checksum value+algorithm) **MUST** be modeled as separate `sh:NodeShape` definitions referenced via `sh:node` from the parent property constraint.
- Shapes are open — additional properties beyond those specified are permitted (do **not** set `sh:closed true`).
- Use `sh:minCount` and `sh:maxCount` for cardinality enforcement.
- Use `sh:datatype` for typed literal constraints (`xsd:date`, `xsd:decimal`).
- Use `sh:class` for class membership constraints (`skos:Concept`).
