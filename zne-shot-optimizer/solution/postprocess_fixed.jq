# Post-process raw analysis results into final report format
# Adds derived metrics including variance improvement ratio
with_entries(
  .value.allocation.improvement_ratio = (
    .value.allocation.variance_uniform / .value.allocation.variance_optimal
  )
)
