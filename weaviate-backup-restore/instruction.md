The Weaviate vector database binary is pre-installed at `/usr/local/bin/weaviate`. A collection schema specification is at `/app/schema_spec.json` and a deterministic data seeding script at `/app/seed_data.py`.

Deploy two independent, standalone Weaviate instances on this host — a primary on port `8080` and a secondary on port `8079`. Create the collections defined in the schema specification on the primary, populate it using the seed script (which requires collections and tenants to already exist on the primary), then replicate the complete database state to the secondary instance.

The secondary must be a fully independent single-node deployment — not a cluster peer of the primary. Every aspect of the primary's state must be faithfully reproduced on the secondary: collection schemas with all HNSW vector index parameters (efConstruction, maxConnections, ef, distance metric), BM25 inverted index tuning (b, k1), property-level indexing and tokenization configurations, multi-tenancy settings, tenant assignments and activity states, all objects with their original UUIDs, and complete vector embeddings.

Both instances must be running and accessible when the task is complete.