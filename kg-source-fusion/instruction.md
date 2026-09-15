A movie-domain integration problem: a seed knowledge graph (`/app/seed.nt`, N-Triples), a target ontology (`/app/ontology.ttl`), three external data sources in `/app/sources/` (RDF/Turtle, JSON records, CSV), known entity correspondences (`/app/matches/known_matches.tsv`), and integration parameters (`/app/config.yaml`).

Implement `/app/pipeline.py` to fuse all sources into a single, deduplicated knowledge graph conforming to the target ontology. Produce:

- `/app/output/fused.nt` — unified KG in N-Triples where equivalent entities across all sources are merged, conflicting property values are correctly resolved, and all predicates use the target ontology vocabulary
- `/app/output/match_clusters.json` — entity equivalence clusters as `{"clusters": [{"canonical": "<uri>", "members": ["<uri>", ...]}, ...]}`

Study `/app/config.yaml`, the ontology, and all input sources to understand source definitions, integration policies, schema mappings, and property classifications.