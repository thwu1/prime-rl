[
  [.nodes, .sources, .exposures] | add | to_entries[] |
  .key as $child |
  .value.depends_on.nodes[]? |
  [$child, .]
] | sort | .[] | @tsv
