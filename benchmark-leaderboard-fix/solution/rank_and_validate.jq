#
# Rank models using config-driven sort criteria, format output, validate.
# Input: metrics JSON array
# Config: $config[0] via --slurpfile

# Build sort criteria array from config
$config[0].ranking as $ranking |
([$ranking.primary_sort] + ($ranking.tiebreakers // [])) as $criteria |

# Sort by dynamic fields with ascending/descending support
sort_by(
    . as $model |
    [$criteria[] |
     .field as $f | .order as $o |
     if $o == "descending"
     then -($model[$f])
     else ($model[$f])
     end
    ]
) |

# Assign 1-based ranks
to_entries | map(
    .value + {"rank": (.key + 1)}
) |

# Format output fields: rates as percentages with specified precision
map({
    rank,
    model_id,
    resolved_rate_pct: ((.resolved_rate * 1000 | round) / 10),
    sem_pct: ((.sem * 10000 | round) / 100),
    pass_at_k_pct: ((.pass_at_k * 1000 | round) / 10),
    cost_per_problem: ((.cost_per_problem * 10000 | round) / 10000),
    contaminated_count,
    decontaminated_resolved_rate_pct: ((.decontaminated_resolved_rate * 1000 | round) / 10),
    unique_solves
}) |

# Validate constraints
if any(.[]; .resolved_rate_pct < 0 or .resolved_rate_pct > 100)
then error("resolved_rate_pct out of range [0, 100]")
elif any(.[]; .sem_pct < 0)
then error("negative sem_pct")
elif any(.[]; .cost_per_problem < 0)
then error("negative cost_per_problem")
else .
end
