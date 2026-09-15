{
  node_count: (.nodes | length),
  by_resource_type: (
    [.nodes | to_entries[].value.resource_type] |
    group_by(.) |
    map({(.[0]): length}) |
    add
  ),
  root_nodes: [
    .nodes | to_entries[] |
    select((.value.depends_on.nodes // []) | length == 0) |
    .key
  ] | sort,
  leaf_nodes: [
    .child_map | to_entries[] |
    select(.value | length == 0) |
    .key
  ] | sort,
  max_fan_out: ([.child_map | to_entries[] | .value | length] | max),
  max_fan_out_nodes: (
    ([.child_map | to_entries[] | .value | length] | max) as $m |
    [.child_map | to_entries[] | select((.value | length) == $m) | .key] | sort
  ),
  edge_count: [.nodes | to_entries[] | (.value.depends_on.nodes // []) | length] | add
}
