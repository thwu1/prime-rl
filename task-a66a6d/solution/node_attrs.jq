([.nodes, .sources, .exposures] | add) as $all |
[
  $all | to_entries[] |
  .key as $uid | .value as $node |
  (if $node.resource_type == "test" and ($node.depends_on.nodes | length) > 0 then
    (($node.tags // []) + ($all[$node.depends_on.nodes[0]].tags // [])) | unique | sort
  else
    ($node.tags // []) | sort
  end) as $etags |
  [$uid, $node.resource_type, ($node.fqn | last), ($node.execution_time_seconds // 0), ($etags | join(","))]
] | sort_by(.[0]) | .[] | @tsv
