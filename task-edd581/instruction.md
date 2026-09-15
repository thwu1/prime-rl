Five SAST scanners have been run against a Java benchmark application. Their scan results, in five different formats, are at `/app/tool_results/`. Ground-truth vulnerability labels are in `/app/expected_results.csv`. A CWE taxonomy tree is in `/app/cwe_hierarchy.xml` (namespace-qualified). A tiered security policy is in `/app/policy.yaml`.

Produce `/app/audit_report.json` that evaluates each scanner's detection accuracy using hierarchy-aware CWE matching and assesses compliance against the policy.

The report must contain:

- **`tools`**: Per-tool object keyed by scanner name. Each has `overall` and `categories` sub-objects with confusion matrix counts (`tp`, `fp`, `tn`, `fn`) and derived metrics (`tpr`, `fpr`, `precision`, `youdens_j`). Per-tool overall TPR/FPR are macro-averaged across categories; overall counts are category sums.
- **`rankings`**: `by_youdens_j` — list of tool names sorted by overall Youden's J descending.
- **`anomalies`**: List of objects `{tool, category, reason, category_fpr, tool_mean_fpr, tool_std_fpr}` for categories whose FPR is a statistical outlier within their tool.
- **`compliance`**: Per-tool `{verdict, failing_categories}`. Verdict is `pass`, `fail`, or `conditional` based on tier severity. Each failing category entry includes `{category, tier, metric, value, threshold}`.
- **`hierarchy_match_stats`**: `{direct_matches, ancestor_matches, descendant_matches}` aggregated across all tools.

## Key requirements

- CWE matching is hierarchy-aware with depth constraints from the policy. A reported CWE matches an expected CWE if it equals it (direct), is a descendant within `max_descendant_depth`, or an ancestor within `max_ancestor_depth`. When a tool reports multiple CWEs for one test case, prefer the strongest hierarchy match (direct > descendant > ancestor).
- Each test case produces exactly one classification (TP/FP/TN/FN) per tool.
- Zero denominators yield 0.0.
- Tool output formats are heterogeneous and undocumented — inspect each file to determine the parsing approach.