# Edge cost computation using CEB cost model C (corrected)
#

def nilj_c: 0.001;
def clamp: if . <= 0 then 1 else . end;

.subplans as $sp |
[$sp | to_entries[] | {key: .key, tables: (.key | split(",")), cards: .value}] as $all |

[
  $all[] as $sup |
  $all[] as $sub |
  select(($sup.tables | length) == (($sub.tables | length) + 1)) |
  select([$sub.tables[] | . as $t | ($sup.tables | index($t)) != null] | all) |
  ([$sup.tables[] | select(. as $t | ($sub.tables | index($t)) == null)] | sort | join(",")) as $diff |

  # Cardinalities with zero clamping (FIX 1)
  ($sp[$sub.key].actual | clamp) as $c1t |
  ($sp[$diff].actual | clamp) as $c2t |
  ($sp[$sub.key].estimated | clamp) as $c1e |
  ($sp[$diff].estimated | clamp) as $c2e |
  ($sub.tables | length) as $len1 |
  ($diff | split(",") | length) as $len2 |

  # NILJ with correct formula (FIX 2): when len1==1, use c2+nilj*c1
  (if $len1 == 1 then ($c2t + nilj_c * $c1t)
   elif $len2 == 1 then ($c1t + nilj_c * $c2t)
   else null end) as $nilj_t |
  (if $nilj_t != null then [($nilj_t), ($c1t * $c2t)] | min
   else ($c1t * $c2t) end) as $true_cost |

  (if $len1 == 1 then ($c2e + nilj_c * $c1e)
   elif $len2 == 1 then ($c1e + nilj_c * $c2e)
   else null end) as $nilj_e |
  (if $nilj_e != null then [($nilj_e), ($c1e * $c2e)] | min
   else ($c1e * $c2e) end) as $est_cost |

  {sup: $sup.key, sub: $sub.key, diff: $diff,
   true_cost: $true_cost, est_cost: $est_cost}
] as $edges |

# Q-errors with zero clamping (FIX 1)
[$sp | to_entries[] |
  (.value.actual | clamp) as $a |
  (.value.estimated | clamp) as $e |
  {subplan: .key, qerror: ([($a / $e), ($e / $a)] | max)}
] as $qerrors |

{name: .name, edges: $edges, qerrors: $qerrors}
