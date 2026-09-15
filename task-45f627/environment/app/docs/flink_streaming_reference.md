# Apache Flink Streaming Join State & Optimization Reference

## Streaming Join State Model

In Apache Flink's streaming SQL runtime, each binary streaming join operator
maintains two independent state buffers -- one for its left input (inputs[0])
and one for its right input (inputs[1]). Incoming records from each stream are
retained in their respective buffer for the duration of the configured state
time-to-live (TTL). During this retention window, each arriving record on one
side is probed against all buffered records on the opposite side to find
matches according to the join predicate.

The steady-state memory footprint of each side's buffer is determined by the
volume of data that accumulates over the TTL window: the input arrival rate,
the retention duration, and the per-record serialized size together determine
the buffer's memory footprint.

### Cascaded Join State Propagation

When joins are arranged in a cascade -- the output of one join node feeds as
an input to the next join node downstream -- the downstream join's input
characteristics on that side are determined by the upstream join's declared
output properties (`estimated_output_rate` and `estimated_output_row_size` in
the execution plan). These declared values, not the original source rates,
govern the downstream join's state buffer sizing on that side.

For non-join intermediate nodes (`AsyncMLPredict`, `Calc`), the effective rate
and row size propagate transparently from their single input (inputs[0]).

## Node Types in Execution Plans

- **Source**: Originates data at a declared `rate_per_second` with a known
  `avg_row_size_bytes`
- **Join**: Binary join with left side at `inputs[0]` and right side at
  `inputs[1]`. Has `join_type` (INNER, LEFT, RIGHT, FULL) and `join_keys`
  mapping column names between sides. Declares `estimated_output_rate` and
  `estimated_output_row_size`.
- **AsyncMLPredict**: Asynchronous ML inference operator with `target_qps`,
  `p99_latency_seconds`, `avg_request_size_bytes`, and `max_ops_per_subtask`.
- **Calc**: Pass-through computation node (inherits upstream characteristics)
- **Sink**: Terminal output node

## Multi-Join Optimization (Flink 2.1 StreamingMultiJoinOperator)

Apache Flink 2.1 introduced a multi-way join operator that can replace
eligible groups of cascaded binary joins with a single consolidated operator.
The multi-way operator accesses source data directly, completely bypassing
the intermediate join results that would otherwise be materialized and
buffered by the individual binary operators.

### Eligibility Constraints

A contiguous sub-group of a cascaded join chain is eligible for multi-join
consolidation when all of the following hold:

1. The sub-group contains at least two join operators (joining three or more
   original input streams)
2. Every join operator in the sub-group uses either INNER or LEFT join
   semantics (RIGHT and FULL joins are excluded)
3. All join operators in the sub-group share at least one common join key
   column name across their key column sets. A join's key column set is the
   union of all left and right column names in its `join_keys` array. When
   multiple common key columns exist, the lexicographically first one is
   reported.

When a maximal chain of cascaded joins cannot be fully consolidated (e.g.,
because a join in the middle uses FULL semantics, or because a key column
mismatch breaks the common-key requirement), the optimizer must identify
the largest possible contiguous sub-groups within the chain that satisfy all
three constraints.

### Consolidated State Model

Under cascaded binary joins, each operator in the chain maintains state
buffers for both of its inputs -- including buffers sized according to
intermediate join results produced by upstream operators. The multi-way join
eliminates all intermediate result state, maintaining only the state for the
leaf source streams that feed into the consolidated group. Nodes outside the
eligible group that feed into it are treated as leaf inputs for state
accounting.

## Async ML_PREDICT Capacity Planning

Flink's asynchronous ML_PREDICT operator processes inference requests with
bounded concurrency. Capacity planning determines the minimum resources
needed to sustain a target throughput given the observed processing latency.

Applying queueing-theoretic principles (Little's Law), the minimum number of
requests that must be simultaneously in-flight to sustain the target QPS at
the observed P99 latency -- adjusted by a configurable safety margin --
gives the required queue depth (taken as the ceiling integer).

From the queue depth, minimum subtask parallelism is derived by dividing by
the per-subtask operation limit (ceiling). Memory allocation per subtask is
based on the subtask's operation capacity and the average request payload
size. Total async memory across all in-flight requests is derived from the
queue depth and per-request payload size.
