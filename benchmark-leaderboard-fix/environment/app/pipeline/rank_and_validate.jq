# Implement: rank models and validate the leaderboard.
#
# Input: metrics.json (JSON array of model result objects)
#   Each object has: model_id, resolved_rate, sem, pass_at_k,
#   cost_per_problem, contaminated_count, decontaminated_resolved_rate,
#   unique_solves
#
# Config: available as $config[0] (loaded via --slurpfile)
#   $config[0].ranking.primary_sort: {field, order}
#   $config[0].ranking.tiebreakers: [{field, order}, ...]
#   order is "ascending" or "descending"
#
# Output: JSON array of leaderboard entries, each with:
#   rank, model_id, resolved_rate_pct (1 decimal), sem_pct (2 decimals),
#   pass_at_k_pct (1 decimal), cost_per_problem (4 decimals),
#   contaminated_count, decontaminated_resolved_rate_pct (1 decimal),
#   unique_solves
#
# Requirements:
#   - Sorting must be config-driven with dynamic field access (not hardcoded)
#   - Validate: rates in [0,100], sem >= 0, cost >= 0
#   - Ranks are 1-based, assigned after sorting
"TODO"
