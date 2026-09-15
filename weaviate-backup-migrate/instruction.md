A Weaviate vector database backup was captured from a production 4-node cluster. The backup must be restored onto a target cluster with a different node topology, available module set, resource profile, and tokenizer support. The backup descriptor is not directly compatible with the target environment.

## Input Files

- `/app/backup/backup_descriptor.json` — backup metadata from the source cluster encoding collection schemas (including cross-references between collections, vectorizer assignments, HNSW index configurations with Product Quantization compression settings, property-level tokenization), shard-to-node placements with health metrics (tombstone counts, compaction status), replication topologies, and multi-tenant lifecycle states
- `/app/backup/modules.db` — SQLite database containing the Weaviate module registry: vectorizer specifications (types, default dimensions, lifecycle status) and module-to-module compatibility mappings with priority ordering
- `/app/target_config.yaml` — target cluster specification: node topology, resource constraints (vector cache limits, per-node HNSW memory budget), installed modules, and supported tokenizers

## Required Output

Write `/app/migrate.py` — reads all input sources and produces:

1. `/app/output/backup_descriptor.json` — a backup descriptor fully compatible with the target cluster, conforming to `/app/schemas/backup_descriptor_schema.json`
2. `/app/output/migration_report.json` — a structured audit trail of all modifications, data integrity concerns, and unresolvable constraints, conforming to `/app/schemas/migration_report_schema.json`

The migrated descriptor must satisfy all target cluster constraints: node references, module dependencies, PQ compression parameters (segments must evenly divide vector dimensions after any vectorizer-induced dimension changes), tokenizer assignments (only target-supported tokenizers may remain search-indexed), cross-reference targets (all referenced collections must exist in the output), replication factors, cache limits, and tenant lifecycle rules. Data integrity must be preserved. The report must document every modification applied, every data integrity concern discovered — including cascading effects across cross-collection dependencies, storage-layer health anomalies, and resource budget projections — and every constraint that could not be automatically resolved.