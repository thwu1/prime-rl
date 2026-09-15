([.nodes, .sources, .exposures] | add) as $all |
(reduce ($all | to_entries[]) as $e ({};
  reduce ($e.value.depends_on.nodes[]?) as $parent (.;
    .[$parent] = ((.[$parent] // 0) + 1)
  )
)) as $out_deg |
[
  $all | to_entries[] |
  .key as $uid | .value as $node |
  ($node.depends_on.nodes | length) as $in |
  ($out_deg[$uid] // 0) as $out |
  ($node.execution_time_seconds // 0) as $t |
  [$uid, $in, $out, $t, ($out * $t)]
] | sort_by([-(.[4]), .[0]]) | .[] | @tsv
