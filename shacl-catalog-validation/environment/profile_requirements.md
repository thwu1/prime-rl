# SciDCAT-Env Application Profile v2 — Data Requirements

## Overview

SciDCAT-Env v2 extends DCAT-AP 3.0.1 with additional mandatory constraints for environmental scientific datasets. It targets catalogs aggregating geospatial environmental monitoring data from EU research and reporting programs.

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
| vcard  | http://www.w3.org/2006/vcard/ns# |
| sh     | http://www.w3.org/ns/shacl# |

## Standard DCAT-AP 3.0.1 Mandatory Properties

These remain required:

- **dcat:Catalog**: `dct:title`, `dct:description`, `dct:publisher` (pointing to a `foaf:Agent`)
- **dcat:Dataset**: `dct:title`, `dct:description`
- **dcat:Distribution**: `dcat:accessURL`
- **foaf:Agent**: `foaf:name`

## SciDCAT-Env v2 Extension Requirements

### Dataset

| Property | Requirement |
|----------|-------------|
| Geographic coverage (`dct:spatial`) | At least one. Each must be validated as a complete location: both `locn:geometry` (typed as `geo:wktLiteral`) AND `locn:geographicName` required. Use `sh:node` to reference a nested LocationShape for validation. |
| Temporal coverage (`dct:temporal`) | At least one. Each must include `dcat:startDate` and `dcat:endDate` (both typed as `xsd:date`, NOT `xsd:dateTime`). Additionally, `startDate` must be chronologically ≤ `endDate` — enforce this ordering constraint via a SHACL-SPARQL (`sh:sparql`) rule on the PeriodOfTimeShape. |
| Keywords (`dcat:keyword`) | At least 3 total. Additionally: at least 2 must be in English (`@en`) and at least 1 in German (`@de`). Enforce the per-language requirements using `sh:qualifiedValueShape` with `sh:qualifiedMinCount` and `sh:qualifiedValueShapesDisjoint true`. |
| Theme (`dcat:theme`) | At least one, must be a `skos:Concept` instance. |
| Update frequency (`dct:accrualPeriodicity`) | Exactly one. |
| Spatial resolution (`dcat:spatialResolutionInMeters`) | Exactly one, typed as `xsd:decimal`. |
| Data specification (`dct:conformsTo`) | Exactly one. |
| Creator (`dct:creator`) | At least one agent. |
| Contact point (`dcat:contactPoint`) | Exactly one. Must be validated as a `vcard:Kind` node with `vcard:hasEmail` (`sh:nodeKind sh:IRI`) and `vcard:fn`. Use `sh:node` to reference a nested ContactPointShape. |

### Distribution

| Property | Requirement |
|----------|-------------|
| Media type (`dcat:mediaType`) | Exactly one. This is a mandatory property — any constraint enforcing it must use `sh:Violation` severity (the SHACL default), not `sh:Warning`. |
| File format (`dct:format`) | Exactly one. |
| File size (`dcat:byteSize`) | Exactly one, typed as `xsd:nonNegativeInteger`. |
| Integrity checksum (`spdx:checksum`) | Exactly one. Each checksum must include both `spdx:checksumValue` (camelCase, not `checksum_value`) and `spdx:algorithm`. |
| Conditional conformance (`dct:conformsTo`) | Required when `dcat:mediaType` is `application/gml+xml` or `application/x-netcdf`. Enforce via a SHACL-SPARQL (`sh:sparql`) constraint that selects distributions with these media types lacking `dct:conformsTo`. This constraint must be active (not `sh:deactivated`). |

### Catalog

| Property | Requirement |
|----------|-------------|
| Geographic coverage (`dct:spatial`) | At least one. |
| Theme taxonomy (`dcat:themeTaxonomy`) | At least one. |
| License (`dct:license`) | Exactly one. |
| Leaf catalog constraint | This catalog MUST NOT use `dct:hasPart` (`sh:maxCount 0`). |
| Closed shape | The CatalogShape must be `sh:closed true` with `sh:ignoredProperties` listing standard DCAT-AP predicates (`rdf:type`, `dct:title`, `dct:description`, `dcat:dataset`, `dct:publisher`, `foaf:homepage`, `dct:issued`, `dct:modified`, `dct:language`). Only explicitly declared property paths and ignored properties are allowed on catalog nodes. |

### Agent (publishers, creators)

| Property | Requirement |
|----------|-------------|
| Contact email (`foaf:mbox`) | Exactly one, as a `mailto:` URI (`sh:nodeKind sh:IRI`). |

## SHACL Implementation Notes

- Use `sh:node` (not `sh:class`) for blank-node validation of nested structures (locations, temporal periods, checksums, contact points). `sh:class` requires an explicit `rdf:type` triple, which blank nodes in DCAT-AP data often lack.
- All SHACL-SPARQL constraints must use `$this` as the focus node variable and include proper `PREFIX` declarations within the SPARQL query body.
- Constraints must not be marked `sh:deactivated true` in production shapes — deactivated constraints are silently skipped during validation.
- Property constraints that enforce mandatory requirements must use `sh:Violation` severity (the default). Constraints with `sh:Warning` severity produce warnings but do NOT cause validation failure (`conforms` remains `true`).
