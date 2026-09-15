Two OWL/RDF-XML ontologies representing product classification schemas are provided at `/app/data/source_ontology.owl` (~90 classes, retail products) and `/app/data/target_ontology.owl` (~100 classes, industrial supply). Both ontologies contain class hierarchies (`rdfs:subClassOf`), lexical annotations (`rdfs:label`, `skos:altLabel`, `rdfs:comment`), disjointness axioms (`owl:disjointWith`), and complex OWL DL constructs: `owl:equivalentClass` definitions composed of `owl:intersectionOf` with `owl:Restriction` (`owl:onProperty` + `owl:someValuesFrom`) constraints, plus additional `rdfs:subClassOf` restriction axioms. These restrictions encode semantic scope constraints (e.g., a class defined as the intersection of a parent class and a property restriction) that alter the denotational semantics of classes beyond what their labels convey.

A labeled reference of 18 concept-pair alignments is at `/app/data/reference_sample.csv`. The full set of 80 candidate pairs to classify is at `/app/data/candidate_pairs.csv`.

Build a system that parses both ontologies — extracting class URIs, full hierarchy, labels, descriptions, disjointness axioms, equivalent class definitions, and property restriction constraints — and classifies each candidate pair into exactly one of five semantic relation types:

- `=` equivalence — concepts denote the same set of instances
- `>` superclass_of — every instance of the target concept is an instance of the source, but not vice versa
- `<` subclass_of — every instance of the source concept is an instance of the target, but not vice versa
- `~` overlap — concepts share some but not all instances
- `!` disjoint — concepts share no instances

Write predictions to `/app/alignment_output.csv` — a CSV file with exactly three columns: `source_id,target_id,relation`.

**Output requirements:**

- Every pair from `/app/data/candidate_pairs.csv` must appear exactly once — no missing pairs and no duplicate pairs
- Each `relation` value must be one of the five symbols: `=`, `>`, `<`, `~`, `!`
- At least 3 distinct relation types must appear across all predictions
- Predictions are evaluated by weighted macro F1 across all five relation types against a held-out gold standard; the minimum passing threshold is 0.45

Correctly classifying the harder pairs — distinguishing subsumption direction between asymmetric hierarchies, detecting overlap at domain boundaries where neither concept subsumes the other, identifying disjointness that requires tracing through cross-ontology domain mappings and inherited disjointness axioms — demands reasoning about OWL restriction scopes, hierarchy depth asymmetries, and structural bridging between differently-organized taxonomies. Surface-level label similarity alone is insufficient.