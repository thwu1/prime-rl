An email archive SQLite database exists at `/app/archive.db`. The schema is undocumented — explore the database to understand its structure, entity relationships, data conventions, and any pre-existing database objects before proceeding. Verify that any views or derived objects you find are correct for your use case before relying on them.

Build a denormalized Parquet analytics layer at `/app/analytics/` and use it to derive analytical results written as JSON to `/app/results/`.

## Parquet Analytics Layer (`/app/analytics/`)

The primary messages dataset must reside under `/app/analytics/messages/` with Hive-style year partitioning (`year=YYYY/` directories). All Parquet files must use Snappy compression on every column, dictionary encoding on string columns with fewer than 100 distinct values, and have column statistics enabled for predicate pushdown. Design additional denormalized files as needed to support the query workload.

## Analytical Queries (`/app/results/`)

**Q1** (`/app/results/q1.json`): **Thread Response Times** — For conversations with ≥ 3 messages, compute the median inter-message time gap in minutes. Categorize each conversation: `"fast"` (median < 60 min), `"medium"` (60 ≤ median < 1440), `"slow"` (median ≥ 1440). Output: `[{category, thread_count, avg_thread_length, avg_median_response_min}]` sorted alphabetically by category.

**Q2** (`/app/results/q2.json`): **Sender Influence via PageRank** — Construct a directed weighted communication graph: edge weight from A to B equals the number of messages A sent with B as a direct recipient. Compute PageRank (damping=0.85, uniform init 1/N, dangling-node mass redistributed uniformly, convergence when max |Δscore| < 1e-8, max 100 iterations). Output top 20 by `pagerank_score` desc (ties: `email` asc): `{email, pagerank_score, messages_sent, messages_received, out_degree, in_degree}` — `messages_received` counts only direct-recipient messages, `out_degree`/`in_degree` count distinct counterpart addresses in direct communications only.

**Q3** (`/app/results/q3.json`): **Label Co-occurrence with Jaccard Similarity** — For messages with 2+ labels, compute pairwise co-occurrence for all unordered label pairs. Top 20 by `co_occurrence_count` desc (ties: `label_a` asc, `label_b` asc). Each entry: `{label_a, label_b, co_occurrence_count, jaccard_similarity}` where `label_a < label_b` alphabetically and Jaccard = |intersection| / |union| over message sets.

**Q4** (`/app/results/q4.json`): **Communication Burstiness** — For each sender who sent ≥ 15 messages, compute inter-message gap durations in hours (chronological order). Calculate burstiness B = (σ − μ) / (σ + μ) where σ = population standard deviation, μ = mean of gap durations. Classify: `"bursty"` (B > 0.2), `"random"` (−0.2 ≤ B ≤ 0.2), `"periodic"` (B < −0.2). Output: `[{category, sender_count, avg_burstiness, avg_messages_per_sender}]` sorted alphabetically by category.

**Q5** (`/app/results/q5.json`): **Attachments by Domain** — Per sender's email domain (only domains with attachments): `{sender_domain, total_messages_with_attachments, total_attachments, distinct_mime_types, avg_attachment_size_bytes, total_attachment_bytes}` sorted by `total_attachments` desc, `sender_domain` asc.