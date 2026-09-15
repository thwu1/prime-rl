Build an evaluation pipeline for the SemTab (Semantic Web Challenge on Tabular Data to Knowledge Graph Matching) competition format. The pipeline must load an RDF knowledge graph encoded in Turtle, implement the OWL 2 and RDFS entailment rules needed to correctly resolve entity identities, class hierarchies, and property hierarchies, and use this reasoning to evaluate system submissions for three annotation tasks: Cell Entity Annotation (CEA), Column Type Annotation (CTA), and Column Property Annotation (CPA).

## Data

All data is in `/data/`:

- `kg.ttl` — RDF knowledge graph in Turtle format using the Wikidata URI namespace (`http://www.wikidata.org/entity/` for entities/classes, `http://www.wikidata.org/prop/direct/` for properties). Contains entity declarations, `owl:sameAs` identity assertions, `rdfs:subClassOf` class hierarchy, `owl:equivalentClass` class equivalences, `rdfs:subPropertyOf` property hierarchy, and property metadata.
- `eval_ontology.ttl` — OWL ontology defining the vocabulary for the RDF evaluation output.
- `tables/` — CSV table files (header row + data rows)
- `gt_cea.csv` — Ground truth CEA: `filename,row_id,col_id,entity_id`
- `gt_cta.csv` — Ground truth CTA: `filename,col_id,class_id`
- `gt_cpa.csv` — Ground truth CPA: `filename,source_col,target_col,property_id`
- `challenge_categories.json` — Maps challenge categories to `"table:row:col"` keys for CEA cells
- `submissions/` — System submissions: `system_{A,B,C}_{cea,cta,cpa}.csv`
- `evaluation_spec.json` — Output format specification and evaluation semantics

Annotations use short Wikidata IDs (e.g., `Q100`, `P131`). The knowledge graph uses full URIs.

## Output

Write two files:

1. **`/app/results.json`** — Per-system metrics (precision, recall, F1, coverage, abstention_rate) for CEA/CTA/CPA, F1 rankings (descending), and per-category CEA accuracy (correct/total/accuracy per challenge category per system).

2. **`/app/results.nt`** — N-Triples RDF encoding evaluation results using the vocabulary from `eval_ontology.ttl`. One `eval:Evaluation` resource per (system, task) pair with URI pattern `http://example.org/eval#{system}_{task}`, carrying all properties defined in the ontology with appropriate XSD-typed literals.

## Evaluation Requirements

The knowledge graph uses standard W3C OWL 2 and RDFS constructs whose formal semantics determine how matches are resolved across all three annotation tasks. The KG contains `owl:sameAs`, `rdfs:subClassOf`, `owl:equivalentClass`, and `rdfs:subPropertyOf` — each with well-defined entailment rules that the evaluator must implement to produce correct results. Systems may submit `ABSTAIN` (excluded from precision denominator) or `NIL` (matches only NIL, case-insensitive).

Refer to `evaluation_spec.json` for the output format and metric definitions.