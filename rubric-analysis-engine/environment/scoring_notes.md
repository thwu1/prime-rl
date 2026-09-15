
# Evaluation Scoring — Internal Notes (Draft)

These notes document key aspects of the hierarchical rubric scoring system
used for the paper replication benchmark. This is an incomplete working
document; consult the verified reference values in the database for
authoritative ground truth.

## Rubric Structure

Rubrics are hierarchical trees stored as an adjacency list in the
`rubric_nodes` table. Each row has a `parent_id` pointing to its parent
node (NULL for the root). Leaf nodes — those with no children — have a
non-null `task_category` field.

Each node carries a `weight` value. Weights encode relative importance
among siblings under the same parent, not absolute importance. A node with
weight 6 under a parent whose children sum to 12 carries the same relative
share as a node with weight 1 under a parent whose children sum to 2.

## Score Propagation

Leaf scores come from binary grading records (0 or 1). Scores propagate
upward through the tree to produce a single root-level aggregate.

The propagation respects the tree structure: a node's score depends on its
immediate children, not on distant descendants directly.

## Leaf Sensitivity

The "sensitivity" of a leaf quantifies how much the root score changes when
that leaf alone flips from 0 to 1. A leaf buried deep in the tree beneath
low-weight ancestors may have surprisingly low sensitivity despite a large
local weight. Conversely, a leaf with modest local weight under
high-weight ancestors can dominate the overall score.

The sensitivity values across all leaves of a rubric should sum to exactly
1.0 (since flipping every leaf from 0 to 1 takes the root from 0 to 1).

## Category Analysis

Each leaf belongs to one of three task categories: "Code Development",
"Execution", or "Result Match". A meaningful category-level score should
reflect each leaf's structural importance in the tree, not merely count
how many leaves in that category were satisfied.

## Inter-Judge Agreement

When comparing two sets of grading decisions, standard binary classification
metrics apply. Cohen's kappa adjusts raw agreement for the level of
agreement expected by chance, which depends on each individual rater's
tendency to assign positive versus negative scores.

The scoring policy configuration at `/app/config/policy.yaml` determines
the precise methodology for agreement computation, including whether
observations should carry equal weight or be weighted by structural
importance.

## Pipeline Architecture

Two legacy scoring implementations exist:

- `scorer.py` — Python implementation with CLI subcommands for each
  analysis type. Simpler codebase but may oversimplify the tree handling.
- `pipeline.sh` — Shell pipeline using sqlite3 recursive CTEs and jq
  for JSON formatting. Structurally more faithful to the tree model but
  has its own issues with output formatting.

Neither tool produces fully correct results across all output types.
Compare both against the verified reference values in the database to
determine which parts of each implementation are trustworthy. The two
tools may be correct on different subsets of the analysis.
