# Edge cost computation using CEB cost model C
# Input: query JSON with .subplans map
# Output: JSON with .edges (true/estimated costs) and .qerrors
#

def nilj_c: 0.001;

.subplans as $sp |

# Parse subplan entries into structured records
[$sp | to_entries[] | {key: .key, tables: (.key | split(",")), cards: .value}] as $all |

# Build subset graph edges: superset(size N) -> subset(size N-1)
[
  $all[] as $sup |
  $all[] as $sub |
  select(($sup.tables | length) == (($sub.tables | length) + 1)) |
  select([$sub.tables[] | . as $t | ($sup.tables | index($t)) != null] | all) |

  # diff = tables in sup but not in sub (the newly joined table)
  ([$sup.tables[] | select(. as $t | ($sub.tables | index($t)) == null)] | sort | join(",")) as $diff |

  # Fetch cardinalities for subset (node1) and diff (node2)
  ($sp[$sub.key].actual) as $c1t |
  ($sp[$diff].actual) as $c2t |
  ($sp[$sub.key].estimated) as $c1e |
  ($sp[$diff].estimated) as $c2e |
  ($sub.tables | length) as $len1 |
  ($diff | split(",") | length) as $len2 |

  # NILJ cost with true cardinalities
  (if $len1 == 1 then ($c1t + nilj_c * $c2t)
   elif $len2 == 1 then ($c1t + nilj_c * $c2t)
   else null end) as $nilj_t |
  (if $nilj_t != null then [($nilj_t), ($c1t * $c2t)] | min
   else ($c1t * $c2t) end) as $true_cost |

  # NILJ cost with estimated cardinalities
  (if $len1 == 1 then ($c1e + nilj_c * $c2e)
   elif $len2 == 1 then ($c1e + nilj_c * $c2e)
   else null end) as $nilj_e |
  (if $nilj_e != null then [($nilj_e), ($c1e * $c2e)] | min
   else ($c1e * $c2e) end) as $est_cost |

  {sup: $sup.key, sub: $sub.key, diff: $diff,
   true_cost: $true_cost, est_cost: $est_cost}
] as $edges |

# Q-errors: max(actual/estimated, estimated/actual)
[$sp | to_entries[] |
  (.value.actual) as $a |
  (.value.estimated) as $e |
  {subplan: .key, qerror: ([($a / $e), ($e / $a)] | max)}
] as $qerrors |

{name: .name, edges: $edges, qerrors: $qerrors}
