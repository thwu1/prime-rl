# Post-process aggregate ranking output to enforce schema compliance
# BUG: per_benchmark_ranks field is not included in the output
[.[] | {
  fuzzer,
  mean_rank: ((.mean_rank * 100 | round) / 100),
  total_novelty: ((.total_novelty * 10000 | round) / 10000)
}]
