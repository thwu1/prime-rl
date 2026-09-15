"""
Cost Model Reference Implementation for the Multi-Operator Query Optimizer.

All cost parameters MUST be read from the config table in /data/catalog.db.
Table/column/index statistics are also in catalog.db.

Physical Property Rules:
- A sequential scan's output is sorted on the table's clustered_on column
  (from the tables table in catalog.db). NULL means unsorted.
- An index scan's output is sorted on the index column (not the clustered column).
- A Filter node preserves the sort order of its child.
- After any join (hash or merge), the output is NOT sorted on any column.

Operator Eligibility:
- Index scan is valid only when a B-tree index exists on the filtered column
  AND the filter selectivity (1/distinct_values) is strictly less than the
  index_selectivity_threshold from the config table.
- Sort-merge join requires both inputs sorted on their respective join columns.
  If an input is not sorted on the join column, the join requires an explicit
  sort, whose cost is added to the merge join cost.
- Hash join always builds on the smaller-cardinality input.

"""

import math


def seq_scan_cost(pages, rows, seq_page_cost, cpu_tuple_cost):
    """Sequential scan: read all pages sequentially + process all tuples."""
    return seq_page_cost * pages + cpu_tuple_cost * rows


def index_scan_cost(selectivity, table_pages, index_pages, table_rows,
                    random_page_cost, cpu_index_cost):
    """
    Index scan for an equality filter with a B-tree index.
    Random I/O proportional to selectivity for index and table pages.
    """
    est_rows = round(table_rows * selectivity)
    io = random_page_cost * (math.ceil(index_pages * selectivity)
                             + math.ceil(table_pages * selectivity))
    cpu = cpu_index_cost * est_rows
    return io + cpu


def filter_cost(input_rows, cpu_operator_cost):
    """CPU cost to evaluate a filter predicate over input rows."""
    return cpu_operator_cost * input_rows


def hash_join_cost(build_rows, probe_rows, cpu_tuple_cost,
                   hash_build_factor, hash_probe_factor):
    """
    Hash join: hash the build side (smaller input), probe from the larger.
    build_rows MUST be <= probe_rows.
    """
    return cpu_tuple_cost * (hash_build_factor * build_rows
                             + hash_probe_factor * probe_rows)


def sort_merge_join_cost(left_rows, right_rows, left_sorted, right_sorted,
                         cpu_tuple_cost, merge_cpu_factor, sort_cpu_factor):
    """
    Sort-merge join: merge two sorted streams. If an input is not already
    sorted on the join column, add external sort cost for that side.
    """
    cost = cpu_tuple_cost * merge_cpu_factor * (left_rows + right_rows)
    if not left_sorted:
        cost += sort_cost(left_rows, cpu_tuple_cost, sort_cpu_factor)
    if not right_sorted:
        cost += sort_cost(right_rows, cpu_tuple_cost, sort_cpu_factor)
    return cost


def sort_cost(rows, cpu_tuple_cost, sort_cpu_factor):
    """External sort: O(N log N) with configurable multiplier."""
    if rows <= 1:
        return 0.0
    return sort_cpu_factor * cpu_tuple_cost * rows * math.log2(rows)


def join_cardinality(left_card, right_card, distinct_values):
    """Equi-join cardinality: |left| * |right| / distinct_values."""
    return round(left_card * right_card / distinct_values)


def filter_cardinality(input_card, distinct_values):
    """Equality filter cardinality: |input| / distinct_values."""
    return round(input_card / distinct_values)
