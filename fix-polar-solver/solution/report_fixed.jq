# Transform sqlite3 JSON output into evaluation report
# Input: array of {name, avg_orthogonality_error, stability_metric, optimal_restarts_1}
#        (already sorted by avg_orthogonality_error ascending)
# Output: {configurations: [...with rank and parsed restarts...]}
{
  configurations: [to_entries[] | .value + {
    rank: (.key + 1),
    optimal_restarts_1: (.value.optimal_restarts_1 | fromjson)
  }]
}
