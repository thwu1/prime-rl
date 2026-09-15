# Assemble final leaderboard JSON from scored data
# Input: scored.json with unsorted rankings and task_difficulty
# Output: leaderboard.json with sorted, ranked, and rounded data

.num_tasks as $n

| .rankings |= (
    sort_by(.resolved_rate)
    | [to_entries[] | .value + {
        rank: (.key + 1),
        contamination_fraction: (.value.num_contaminated_tasks / $n)
      }]
  )

| .task_difficulty |= sort_by(-.mean_solve_rate)

| .rankings |= [.[] |
    .resolved_rate = ((.resolved_rate * 100000 | round) / 100000) |
    .sem = ((.sem * 100000 | round) / 100000) |
    .pass_at_1 = ((.pass_at_1 * 100000 | round) / 100000) |
    .pass_at_3 = ((.pass_at_3 * 100000 | round) / 100000) |
    .pass_at_5 = ((.pass_at_5 * 100000 | round) / 100000) |
    .contamination_fraction = ((.contamination_fraction * 100000 | round) / 100000)
  ]

| .task_difficulty |= [.[] |
    .mean_solve_rate = ((.mean_solve_rate * 100000 | round) / 100000)
  ]
