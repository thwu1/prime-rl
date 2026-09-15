A NuBBE biochemical knowledge graph deployment at `/app/data/` has been flagged for a pre-deployment conformance audit. Analyze the OWL ontology for structural defects, cross-validate the knowledge base against the ontology schema, and evaluate link prediction quality. Write all findings to `/app/report.json`.

## Data

- `/app/data/ontology.ttl` — OWL ontology (Turtle format)
- `/app/data/kb.nt` — Knowledge base (N-Triples format)
- `/app/data/predictions/` — Link prediction output CSVs from graph embedding experiments

## `/app/report.json`

```json
{
  "ontology": {
    "num_classes": "<int>",
    "num_datatype_properties": "<int>",
    "max_hierarchy_depth": "<int>",
    "broken_references": [
      {"class": "<local name>", "target": "<local name>"}
    ]
  },
  "conformance": {
    "property_name_mismatches": [
      {"ontology_name": "<str>", "kb_name": "<str>"}
    ]
  },
  "kb": {
    "num_compounds": "<int>",
    "num_triples": "<int>",
    "lipinski_violators": "<sorted int list>"
  },
  "evaluation": {
    "metrics": [
      {"algorithm": "<str>", "stage": "<str>", "hits_at_1": "<float>", "hits_at_3": "<float>", "mrr": "<float>"}
    ],
    "best_hits1_algorithm": "<str>"
  }
}
```

**Ontology**: Count OWL classes and datatype properties scoped to the ontology's own namespace. `broken_references` lists classes whose `rdfs:subClassOf` target is not declared as an `owl:Class` in the ontology (`owl:Thing` excluded); sorted by class local name. `max_hierarchy_depth` counts edges in the longest subclass chain where both endpoints are declared classes.

**Conformance**: Cross-reference property URIs used in the KB against `owl:DatatypeProperty` declarations in the ontology. Report properties present in both whose local names differ only in letter casing.

**Knowledge Base**: Parse the instance data. Count distinct compounds and total data triples. Identify compounds with `numberOfLipinskiViolations > 0`.

**Evaluation**: For each prediction CSV, compute hits@k (k=1,3) and MRR. MRR averages reciprocal rank only over queries where the true target appears in the predicted ranking. Aggregate by (algorithm, stage) pair across all files. `best_hits1_algorithm` has the highest mean hits@1 across all its stages.