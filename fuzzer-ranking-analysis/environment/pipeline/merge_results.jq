# Merge statistical test results and computed metrics into final output
# Derives ranking from average ranks (best = lowest rank first)
($stats[0].average_ranks | to_entries | sort_by(.value) | reverse | map(.key)) as $ranking |
($stats[0] + $metrics[0]) + {"ranking": $ranking}
