A SQLite database at `/app/data/treebank.db` contains weighted directed graph instances. Inspect its schema to understand the data layout. See `/app/spec.md` for mathematical definitions.

Each instance models a sentence as a directed graph with nodes 0 (root) through n (words) and a score matrix of log-weights for potential head-dependent arcs. An arborescence is a directed spanning tree rooted at 0 where every non-root node has exactly one incoming arc and all paths lead to root. Each tree's unnormalized probability is the product of `exp(score[i][j])` for its arcs.

Create `/app/arborescence.py` exposing functions that take numpy score arrays of shape `(n+1, n+1)`:
- `log_partition(scores)` -- log of the total weight summed over all valid arborescences
- `arc_marginals(scores)` -- marginal probability of each directed arc under the distribution
- `entropy(scores)` -- Shannon entropy in nats
- `map_tree(scores)` -- highest-weight arborescence as a head list (`result[0] = -1`)
- `expected_attachment_score(scores, gold_heads)` -- expected fraction of correct head assignments
- `kl_divergence(scores_p, scores_q)` -- KL(P||Q) between two arborescence distributions

Create `/app/pipeline.py` that reads all instances from the SQLite database, runs every computation, and:
- Populates new database tables: `computed_partition(instance_id TEXT, log_z REAL)`, `computed_entropy(instance_id TEXT, entropy_nats REAL)`, `computed_map_heads(instance_id TEXT, node INTEGER, head INTEGER)`, `computed_eas(instance_id TEXT, score REAL)`, `computed_kl(instance_id_p TEXT, instance_id_q TEXT, kl_value REAL)` -- KL for all ordered pairs of instances sharing the same node count
- Renders each instance's MAP tree as `/app/output/{instance_id}_map.svg` using graphviz DOT format with nodes labeled by index and edges labeled with scores

All provided instances must be handled efficiently. Only `numpy` may be used as an external computational dependency.

Execute the full pipeline via: `python3 /app/pipeline.py`