{
  top_tool: {name: .ranking[0].name, youdens_j: .ranking[0].j},
  tool_count: (.ranking | length),
  average_j: ([.ranking[].youdens_j] | add / length),
  blind_spots: [.tools[] | .name as $tool | .categories | to_entries[] | select(.value.tpr == "0") | {tool: $tool, category: .key}]
}
