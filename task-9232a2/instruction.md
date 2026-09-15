A GPU cluster running DeepSeek-style Mixture-of-Experts (MoE) inference with Multi-head Latent Attention (MLA) has been benchmarked. Raw data is in a SQLite database at `/app/cluster.db` (schema documented in `/app/schema.sql`).

Reference source code from FlashMLA — the production KV cache and attention library — is in `/app/sources/`. Notes on expert-parallel communication performance are also there.

Produce `/app/analysis.json` with derived performance metrics for every row in the `workloads` table. The output schema and field semantics are specified in `/app/output_schema.json`.

KV cache byte-per-token values must match the actual storage layouts implemented in the source code. All other metrics must be physically consistent with the MoE+MLA architecture.