# Output Schema: results.json

The output must be a single JSON object containing the sections below. Field names, types, and sort orders must match exactly. You must determine the correct computation methodology for each metric based on your understanding of the SZZ regression-regressor model, the dataset schema, and directed graph theory.

## Implementation Audit

`audit` — object keyed by `v1`, `v2`, `v3`. Each contains four boolean fields:

| Field | Semantic |
|-------|----------|
| `edge_direction_correct` | Edges represent the correct causal direction in the SZZ regressor-regression model |
| `multivalue_parsing_correct` | Multi-valued identifier fields are split using the correct delimiter |
| `fix_classification_correct` | The correct CSV column is used to determine whether a regression-regressor pair has been fixed |
| `path_length_correct` | The longest directed acyclic path computation uses the standard graph-theoretic definition of path length |

## Dataset Metrics

| Field | Type |
|-------|------|
| `total_pairs` | int |
| `fixed_pairs` | int — pairs with identified fix commits |
| `unfixed_pairs` | int — pairs without fix commits |
| `unique_regressor_bugs` | int — distinct regressor bug IDs across all records |

## Directed Graph Structure

| Field | Type |
|-------|------|
| `graph_nodes` | int |
| `graph_edges` | int |
| `max_out_degree_bug` | int — bug ID with the highest out-degree |
| `max_out_degree` | int |
| `top_10_regressors` | list of `[bug_id, out_degree]` — top 10 by out-degree descending, bug ID ascending on ties |

## Component and Cycle Analysis

| Field | Type |
|-------|------|
| `num_weakly_connected_components` | int |
| `largest_wcc_size` | int |
| `num_sccs_with_cycles` | int — strongly connected components with more than one node |
| `has_cycles` | bool |
| `longest_chain_length` | int — path length in the condensation DAG (standard graph-theoretic convention) |

## Boolean Flag Counts

| Field | Type |
|-------|------|
| `no_shared_files_count` | int — records where `NO_FILE_SHARED` is `True` |
| `no_bug_commit_count` | int — records where `NO_BUG` is `True` |

## Cascade Vulnerability

| Field | Type |
|-------|------|
| `orphan_regressor_count` | int — regressor bugs that never appear as regression targets |
| `pure_regression_count` | int — regression targets that never appear as regressors |
| `multi_cause_regression_count` | int — records with more than one distinct regressor bug |
| `transitive_impact_top3` | list of `[bug_id, reachable_descendant_count]` for the 3 highest out-degree nodes (same sort as top_10) |
| `mean_regressor_fanout` | float — mean out-degree of nodes with out-degree > 0, rounded to 2 decimal places |

## Data Quality Triage

`data_quality` — object quantifying internal consistency anomalies in the dataset:

| Field | Type |
|-------|------|
| `self_referencing_pairs` | int — records where the regression bug ID appears among its own regressor bug IDs |
| `no_bug_with_commits` | int — records flagged `NO_BUG=True` yet containing non-empty bug-introducing commit hashes |
| `extrinsic_bug_count` | int — records where no source files are shared between the fix and bug-introducing commits |

## Filtered Graph Analysis

`filtered_graph` — structural metrics for a reliability-filtered subgraph. Records where the causal link between the fix and bug-introducing commits is unsupported by shared file evidence (extrinsic bugs) must be excluded before constructing this graph.

| Field | Type |
|-------|------|
| `nodes` | int |
| `edges` | int |
| `largest_wcc_size` | int |
| `has_cycles` | bool |
| `longest_chain_length` | int |
| `edge_reduction_pct` | float — percentage of original graph edges removed by filtering, rounded to 2 decimal places |

## PageRank Propagation Risk

`pagerank_top10` — list of `[bug_id, score]` for the 10 highest-PageRank nodes in the full (unfiltered) graph. Scores rounded to 6 decimal places. Sorted descending by score, ascending by bug ID on ties.
