"""
Cost Model Formulas for the Query Optimizer.

These functions define the cost and cardinality estimation model.
The optimizer MUST use these exact formulas.

"""


def scan_cost(row_count: int) -> float:
    """Cost of a sequential table scan. One CPU unit per row."""
    return float(row_count)


def filter_cost(input_cardinality: int) -> float:
    """Cost of evaluating a filter predicate over input rows."""
    return input_cardinality * 0.1


def hash_join_cost(build_cardinality: int, probe_cardinality: int) -> float:
    """
    Cost of a hash join. The build side (smaller input) is hashed into
    a hash table, and the probe side (larger input) probes against it.

    build_cardinality: number of rows on the build side (MUST be the smaller input)
    probe_cardinality: number of rows on the probe side (MUST be the larger input)
    """
    return 1.5 * build_cardinality + 1.2 * probe_cardinality


def join_cardinality(left_card: int, right_card: int, distinct_values: int) -> int:
    """
    Estimate the output cardinality of an equi-join.

    Uses the formula: |left| * |right| / distinct_values
    where distinct_values comes from the join_conditions entry in catalog.json.
    """
    return round(left_card * right_card / distinct_values)


def filter_cardinality(input_card: int, distinct_values: int) -> int:
    """
    Estimate the output cardinality after an equality filter.

    Uses the formula: |input| / distinct_values
    where distinct_values is the number of distinct values for the filtered column
    (from the column metadata in catalog.json).
    """
    return round(input_card / distinct_values)
