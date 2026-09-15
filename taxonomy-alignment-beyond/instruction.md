Two product classification ontologies are provided as OWL/RDF-XML files:

- `/app/data/source.owl` — "Generic Product Classification" (GPC), namespace `http://example.org/gpc#`
- `/app/data/target.owl` — "Retail Product Taxonomy" (RPT), namespace `http://example.org/rpt#`

These represent overlapping but structurally distinct retail product taxonomies. They differ in naming conventions, granularity levels, hierarchical depth, and how they partition product domains. Some classes in one ontology have no direct counterpart in the other; many have counterparts that differ in scope or specificity.

## Goal

Produce a multi-relational alignment between classes in the two ontologies. Each discovered correspondence must be classified into exactly one of five relation types:

| Symbol | Meaning | Definition |
|--------|---------|------------|
| `=` | equivalence | classes denote the same set of instances |
| `>` | superclass_of | source class strictly subsumes target class |
| `<` | subclass_of | source class is strictly subsumed by target class |
| `~` | overlap | classes share some but not all instances |
| `%` | disjoint | classes share no instances |

## Output

Write the alignment to `/app/output/alignment.rdf` in OAEI alignment XML format. The file must be well-formed XML with this structure:

- Root element `<rdf:RDF>` with namespace declarations for the alignment namespace (`http://knowledgeweb.semanticweb.org/heterogeneity/alignment`), `rdf`, and `xsd`.
- An `<Alignment>` element containing `<xml>yes</xml>`, `<level>0</level>`, `<type>??</type>`.
- One `<map><Cell>...</Cell></map>` block per correspondence, where each `<Cell>` contains:
  - `<entity1 rdf:resource="..."/>` — full URI from the GPC namespace
  - `<entity2 rdf:resource="..."/>` — full URI from the RPT namespace
  - `<measure rdf:datatype="xsd:float">...</measure>` — confidence score between 0 and 1
  - `<relation>...</relation>` — one of `=`, `>`, `<`, `~`, `%`

## Evaluation Criteria

The alignment is evaluated against a gold standard of 52 expert-curated correspondences distributed across all five relation types. All of the following must be satisfied:

- Output file exists at `/app/output/alignment.rdf` and is valid XML
- Entity URIs use the correct GPC (`http://example.org/gpc#`) and RPT (`http://example.org/rpt#`) namespaces
- At least 20 correspondence cells are produced
- At least 4 of the 5 relation types are represented in the output
- Per-type F1 scores: equivalence F1 >= 0.40, superclass_of F1 >= 0.30, subclass_of F1 >= 0.25
- Weighted macro-F1 across all five relation types >= 0.55 (weighted by gold-standard type frequency)
- Overall precision across all correspondences >= 0.30