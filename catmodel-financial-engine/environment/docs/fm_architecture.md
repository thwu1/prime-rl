# Financial Module Architecture

## Overview

The Oasis Financial Module computes insured losses from ground-up losses by
applying policy terms and conditions through a hierarchical aggregation
structure. The core design is data-driven: the hierarchy, profiles, and
term mappings are all specified via CSV input files.

## Input Files

### fm_programme.csv

Columns: `from_agg_id, level_id, to_agg_id`

Defines the aggregation hierarchy. At each `level_id`, items identified by
`from_agg_id` are grouped into nodes identified by `to_agg_id`. At level 1,
`from_agg_id` corresponds directly to `item_id` values in the ground-up loss
stream.

Levels are processed in ascending order (1, 2, 3, ...). At each subsequent
level, `from_agg_id` refers to the `to_agg_id` from the previous level.

### fm_profile.csv

Columns: `profile_id, calcrule_id, deductible1, deductible2, deductible3,
attachment1, limit1, share1, share2, share3`

Defines calculation profiles. Each profile specifies a `calcrule_id`
(the mathematical function to apply) and the parameter values used by
that function.

### fm_policytc.csv

Columns: `layer_id, level_id, agg_id, profile_id`

Maps each aggregation node (`agg_id` at `level_id`) to a profile. The
`layer_id` column supports multi-layer output; for single-layer
calculations all rows use `layer_id = 1`.

### guls.csv

Columns: `event_id, item_id, sidx, loss`

Ground-up losses. Each row gives the loss for a specific item, event,
and sample index (`sidx`). The sample index is a positive integer
identifying a particular simulation sample.

## Computation

### Per-event, per-sample processing

For each unique `(event_id, sidx)` combination:

1. **Initialize**: Set each item's current loss to its ground-up loss
   value from guls.csv. Items not present in the GUL stream for this
   event/sample have loss = 0.

2. **Level-by-level processing** (levels 1, 2, 3, ...):

   For each aggregation node at the current level:

   a. **Aggregate**: Identify all descendant items of this node. Sum
      their current loss values to obtain the node's aggregate input.

      Descendants are found by tracing the hierarchy downward: the
      node's children are the `from_agg_id` values that map to its
      `to_agg_id`. At level 1, `from_agg_id` values are item IDs
      directly. At higher levels, children are traced recursively
      through lower levels until item IDs are reached.

   b. **Apply calcrule**: Look up the node's profile via fm_policytc.
      Apply the corresponding calculation rule (from fm_profile) to the
      aggregate input to produce the aggregate output. See calcrules.md
      for the formula for each calcrule_id.

   c. **Back-allocate**: Compute the ratio `factor = output / input`.
      If input is zero, factor is zero. Multiply every descendant
      item's current loss by this factor.

      This proportional back-allocation ensures that after applying
      the node's financial terms, individual item losses remain
      proportional to their original contribution to the node's
      aggregate, while their sum equals the node's output.

3. **Output**: After all levels have been processed, each item's
   current loss is its final insured loss value.

### Back-allocation detail

Back-allocation factors cascade multiplicatively through levels. A
factor applied at level 2 multiplies items whose losses were already
adjusted at level 1. This correctly handles compound effects of
financial terms at different hierarchy levels.

When a node's aggregate input is zero (all descendant items have zero
loss), the back-allocation factor is zero. Items with zero loss remain
at zero regardless of the calcrule output.

## Output Format

The output is a CSV with columns: `event_id, item_id, sidx, loss`.

- Losses are floating-point values rounded to 2 decimal places.
- Rows are sorted by event_id ascending, then item_id ascending,
  then sidx ascending.
- Only rows where the rounded loss is greater than zero are included.
