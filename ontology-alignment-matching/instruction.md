Two OWL ontologies describing overlapping water-resource domains are provided at `/app/data/source.owl` (Water Quality Monitoring Ontology) and `/app/data/target.owl` (Hydrological Resource Ontology). They model similar concepts — water bodies, environmental parameters, contaminants, monitoring infrastructure, treatment processes, catchments — but use different naming conventions, different hierarchical structures, and different modeling patterns.

Build a system that produces an alignment between the two ontologies, written to `/app/output/alignment.rdf` in the standard OAEI alignment XML format. A format example is at `/app/data/example_alignment.rdf` and domain details are in `/app/data/README.md`.

The alignment must include:
- **Class correspondences**: equivalence (`=`), subsumption (`<` source narrower, `>` source broader)
- **Property correspondences**: equivalences between `owl:ObjectProperty` elements using label and domain/range analysis

Key difficulties:
- Some classes are defined via `owl:equivalentClass` restrictions (intersections with `owl:someValuesFrom`). Matching these requires analyzing the restriction axioms, not just labels.
- **False-friend classes** exist: classes sharing label tokens that represent semantically different concepts (e.g., electrical conductivity vs. hydraulic conductivity; groundwater spring vs. spring flood). These must NOT be matched.
- Some correspondences are only discoverable through `skos:altLabel` cross-referencing or structural hierarchy analysis.
- Object properties must be aligned using both label similarity and domain/range compatibility.

Requirements:
- Output at `/app/output/alignment.rdf` must be valid OAEI alignment XML
- Class alignment: Precision >= 0.72, Recall >= 0.68, F1 >= 0.70
- At least 10 non-trivial class correspondences detected (where primary labels do not match)
- At least 4 property correspondences detected
- At most 2 false-friend pairs accepted (structural disambiguation required)
- Structural coherence >= 0.65 (hierarchical relationships must be preserved in the alignment)