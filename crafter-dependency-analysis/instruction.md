The Crafter open-world game engine source is at `/app/crafter/` and a SQLite database of RL agent episode data is at `/app/episodes.db`. Four agents (dreamer, ppo, curious, rnd) were evaluated across 10 episodes each. Tables: `episodes(agent, episode, length, reward)` and `achievements(agent, episode, achievement, step)`.

The standard Crafter benchmark uses geometric mean of per-achievement success rates to rank agents, treating all 22 achievements equally despite vast differences in structural difficulty. Your task: audit this methodology by reverse-engineering the achievement prerequisite structure from source code, designing a corrective scoring metric, and evaluating which approach most reliably discriminates between agents under perturbation.

Produce `/app/audit.json` containing:

**`dependency_graph`**: The 22-achievement prerequisite DAG as `{"ach": ["prereq", ...]}`. Prerequisites are NOT explicitly listed anywhere — you must trace action-handling logic in `env.py`, object interaction semantics in `objects.py`, entity spawning rules in `worldgen.py`, and crafting/collection rules in `data.yaml` to determine which achievements structurally require others. All prerequisite lists sorted alphabetically.

**`depths`**: Topological depth of each achievement in the DAG (integer).

**`critical_path`**: Longest dependency chain, listed shallowest to deepest.

**`anomalies`**: Episodes where achievements appear without all direct prerequisites also present. Format: `[{"agent": str, "episode": int, "achievement": str, "missing_prerequisites": [str]}]`, sorted by (agent, episode, achievement).

**`metric_scores`**: Per-agent scores under three approaches — `{"agent": {"geometric_mean": float, "depth_weighted": float, "ips_weighted": float}}`:
- **geometric_mean**: `exp(mean(ln(max(rate_i, 0.01))))` over all 22 achievements
- **depth_weighted**: `sum(rate_i × (depth_i+1)) / sum(depth_i+1)`
- **ips_weighted**: Inverse Propensity Scoring — weight each achievement by `1/max(overall_empirical_rate, 0.05)`, normalize weights to sum to 1, score = weighted sum of per-agent rates. This up-weights rare achievements to correct the geometric mean's equal treatment of trivially-achieved and expert-level goals.

**`rankings`**: Best-to-worst agent ordering per metric. `{"by_geometric_mean": [...], "by_depth_weighted": [...], "by_ips_weighted": [...]}`

**`discrimination`**: For each metric, score gaps between consecutively-ranked agents. `{"metric_name": [{"higher": str, "lower": str, "gap": float, "class": str}]}`. Gap class: `"significant"` if gap > 0.03, else `"marginal"`.

**`stability`**: Leave-one-achievement-out analysis. For each of the 22 achievements, recompute all three rankings with that achievement excluded (averages over 21, renormalized weights). A ranking flip is any pair of agents whose relative order changes versus the full ranking. Format: `{"metric_name": {"flip_count": int, "details": {"ach": [["agent_a","agent_b"]]}}}`. Only include achievements causing flips in details. Agent pairs sorted alphabetically within each pair and across pairs.

**`verdict`**: Synthesized recommendation:
- `most_discriminating`: metric with the most significant gaps (ties: alphabetical)
- `most_stable`: metric with the fewest flip-causing achievements (ties: alphabetical)
- `recommended`: if one metric is both most-discriminating and most-stable, use it; otherwise highest `(significant_count/3) × (1 − flip_count/22)` (ties: alphabetical)
- `pivotal_achievements`: sorted list of achievements whose removal causes flips in ≥2 metrics

Also produce `/app/achievement_dag.dot` (valid Graphviz DOT digraph with prerequisite→dependent edges, must compile with `dot -Tsvg`) and `/app/queries.sql` (SQL queries used, executable against the database).