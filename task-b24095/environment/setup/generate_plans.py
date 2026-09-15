"""
Generate test query plans for the optimizer benchmark.

"""
import json
import os

PLANS_DIR = "/app/plans"
os.makedirs(PLANS_DIR, exist_ok=True)


def write_plan(name, plan_dict):
    with open(os.path.join(PLANS_DIR, f"{name}.json"), "w") as f:
        json.dump(plan_dict, f, indent=2)


# =============================================================================
# Plan 1: filter_pushdown_past_projection
# SELECT a.id, a.name FROM (SELECT id, name, score FROM students) sub WHERE sub.score > 90
# Filter should push below the projection.
# =============================================================================
plan1 = {
    "kind": "filter",
    "predicate": {
        "kind": "binary", "op": ">",
        "left": {"kind": "column", "table": "sub", "column": "score"},
        "right": {"kind": "literal", "value": 90, "dtype": "int"}
    },
    "children": [{
        "kind": "subquery_alias",
        "alias_name": "sub",
        "children": [{
            "kind": "project",
            "projections": [
                {"kind": "column", "table": "students", "column": "id"},
                {"kind": "column", "table": "students", "column": "name"},
                {"kind": "column", "table": "students", "column": "score"}
            ],
            "children": [{
                "kind": "scan",
                "table_name": "students",
                "scan_columns": ["id", "name", "score", "grade"]
            }]
        }]
    }]
}
write_plan("01_filter_push_past_project", plan1)


# =============================================================================
# Plan 2: eliminate_cross_join_to_inner
# SELECT * FROM orders, customers WHERE orders.customer_id = customers.id AND customers.active = true
# Cross join + filter with equijoin predicate -> inner join + residual filter
# =============================================================================
plan2 = {
    "kind": "filter",
    "predicate": {
        "kind": "binary", "op": "AND",
        "left": {
            "kind": "binary", "op": "=",
            "left": {"kind": "column", "table": "orders", "column": "customer_id"},
            "right": {"kind": "column", "table": "customers", "column": "id"}
        },
        "right": {
            "kind": "binary", "op": "=",
            "left": {"kind": "column", "table": "customers", "column": "active"},
            "right": {"kind": "literal", "value": True, "dtype": "bool"}
        }
    },
    "children": [{
        "kind": "join",
        "join_type": "cross",
        "join_condition": None,
        "children": [
            {
                "kind": "scan",
                "table_name": "orders",
                "scan_columns": ["id", "customer_id", "amount", "date"]
            },
            {
                "kind": "scan",
                "table_name": "customers",
                "scan_columns": ["id", "name", "active", "region"]
            }
        ]
    }]
}
write_plan("02_cross_join_to_inner", plan2)


# =============================================================================
# Plan 3: propagate_empty_relation
# SELECT * FROM (SELECT * FROM t WHERE false) sub JOIN orders ON sub.id = orders.id
# The subquery produces an empty relation; the inner join should collapse.
# =============================================================================
plan3 = {
    "kind": "join",
    "join_type": "inner",
    "join_condition": {
        "kind": "binary", "op": "=",
        "left": {"kind": "column", "table": "sub", "column": "id"},
        "right": {"kind": "column", "table": "orders", "column": "id"}
    },
    "children": [
        {
            "kind": "subquery_alias",
            "alias_name": "sub",
            "children": [{
                "kind": "filter",
                "predicate": {"kind": "literal", "value": False, "dtype": "bool"},
                "children": [{
                    "kind": "scan",
                    "table_name": "t",
                    "scan_columns": ["id", "val"]
                }]
            }]
        },
        {
            "kind": "scan",
            "table_name": "orders",
            "scan_columns": ["id", "customer_id", "amount"]
        }
    ]
}
write_plan("03_propagate_empty", plan3)


# =============================================================================
# Plan 4: limit_pushdown_through_union
# SELECT * FROM (SELECT id FROM a UNION ALL SELECT id FROM b) u LIMIT 10
# The LIMIT 10 should be pushed into each branch of the union.
# =============================================================================
plan4 = {
    "kind": "limit",
    "skip": 0,
    "fetch": 10,
    "children": [{
        "kind": "subquery_alias",
        "alias_name": "u",
        "children": [{
            "kind": "union",
            "children": [
                {
                    "kind": "project",
                    "projections": [{"kind": "column", "table": "a", "column": "id"}],
                    "children": [{"kind": "scan", "table_name": "a", "scan_columns": ["id", "val"]}]
                },
                {
                    "kind": "project",
                    "projections": [{"kind": "column", "table": "b", "column": "id"}],
                    "children": [{"kind": "scan", "table_name": "b", "scan_columns": ["id", "val"]}]
                }
            ]
        }]
    }]
}
write_plan("04_limit_push_union", plan4)


# =============================================================================
# Plan 5: eliminate_always_true_filter
# SELECT id, name FROM employees WHERE 1 = 1
# The always-true filter should be eliminated entirely.
# =============================================================================
plan5 = {
    "kind": "filter",
    "predicate": {
        "kind": "binary", "op": "=",
        "left": {"kind": "literal", "value": 1, "dtype": "int"},
        "right": {"kind": "literal", "value": 1, "dtype": "int"}
    },
    "children": [{
        "kind": "project",
        "projections": [
            {"kind": "column", "table": "employees", "column": "id"},
            {"kind": "column", "table": "employees", "column": "name"}
        ],
        "children": [{
            "kind": "scan",
            "table_name": "employees",
            "scan_columns": ["id", "name", "dept", "salary"]
        }]
    }]
}
write_plan("05_eliminate_true_filter", plan5)


# =============================================================================
# Plan 6: eliminate_always_false_filter (replace with empty relation)
# SELECT * FROM products WHERE 1 = 0
# =============================================================================
plan6 = {
    "kind": "filter",
    "predicate": {
        "kind": "binary", "op": "=",
        "left": {"kind": "literal", "value": 1, "dtype": "int"},
        "right": {"kind": "literal", "value": 0, "dtype": "int"}
    },
    "children": [{
        "kind": "scan",
        "table_name": "products",
        "scan_columns": ["id", "name", "price", "category"]
    }]
}
write_plan("06_eliminate_false_filter", plan6)


# =============================================================================
# Plan 7: Combined - filter pushdown through inner join
# SELECT * FROM A JOIN B ON A.id = B.aid WHERE A.x > 5 AND B.y < 10
# Filters should be pushed to respective sides of the join.
# =============================================================================
plan7 = {
    "kind": "filter",
    "predicate": {
        "kind": "binary", "op": "AND",
        "left": {
            "kind": "binary", "op": ">",
            "left": {"kind": "column", "table": "A", "column": "x"},
            "right": {"kind": "literal", "value": 5, "dtype": "int"}
        },
        "right": {
            "kind": "binary", "op": "<",
            "left": {"kind": "column", "table": "B", "column": "y"},
            "right": {"kind": "literal", "value": 10, "dtype": "int"}
        }
    },
    "children": [{
        "kind": "join",
        "join_type": "inner",
        "join_condition": {
            "kind": "binary", "op": "=",
            "left": {"kind": "column", "table": "A", "column": "id"},
            "right": {"kind": "column", "table": "B", "column": "aid"}
        },
        "children": [
            {"kind": "scan", "table_name": "A", "scan_columns": ["id", "x", "z"]},
            {"kind": "scan", "table_name": "B", "scan_columns": ["aid", "y", "w"]}
        ]
    }]
}
write_plan("07_filter_push_join", plan7)


# =============================================================================
# Plan 8: Multi-way cross join elimination
# SELECT * FROM t1, t2, t3 WHERE t1.a = t2.b AND t2.c = t3.d AND t1.x > 100
# Three-way cross join should become two inner joins with residual filter.
# =============================================================================
plan8 = {
    "kind": "filter",
    "predicate": {
        "kind": "binary", "op": "AND",
        "left": {
            "kind": "binary", "op": "AND",
            "left": {
                "kind": "binary", "op": "=",
                "left": {"kind": "column", "table": "t1", "column": "a"},
                "right": {"kind": "column", "table": "t2", "column": "b"}
            },
            "right": {
                "kind": "binary", "op": "=",
                "left": {"kind": "column", "table": "t2", "column": "c"},
                "right": {"kind": "column", "table": "t3", "column": "d"}
            }
        },
        "right": {
            "kind": "binary", "op": ">",
            "left": {"kind": "column", "table": "t1", "column": "x"},
            "right": {"kind": "literal", "value": 100, "dtype": "int"}
        }
    },
    "children": [{
        "kind": "join",
        "join_type": "cross",
        "join_condition": None,
        "children": [
            {
                "kind": "join",
                "join_type": "cross",
                "join_condition": None,
                "children": [
                    {"kind": "scan", "table_name": "t1", "scan_columns": ["a", "x", "y"]},
                    {"kind": "scan", "table_name": "t2", "scan_columns": ["b", "c", "z"]}
                ]
            },
            {"kind": "scan", "table_name": "t3", "scan_columns": ["d", "e"]}
        ]
    }]
}
write_plan("08_multiway_cross_join", plan8)


# =============================================================================
# Plan 9: Left join - filter cannot push to right side (null-extending)
# SELECT * FROM A LEFT JOIN B ON A.id = B.aid WHERE A.x > 5 AND B.y < 10
# A.x > 5 can push to left; B.y < 10 cannot push to right side of LEFT JOIN
# (it's a null-rejecting predicate on the right that converts LEFT->INNER)
# =============================================================================
plan9 = {
    "kind": "filter",
    "predicate": {
        "kind": "binary", "op": "AND",
        "left": {
            "kind": "binary", "op": ">",
            "left": {"kind": "column", "table": "A", "column": "x"},
            "right": {"kind": "literal", "value": 5, "dtype": "int"}
        },
        "right": {
            "kind": "binary", "op": "<",
            "left": {"kind": "column", "table": "B", "column": "y"},
            "right": {"kind": "literal", "value": 10, "dtype": "int"}
        }
    },
    "children": [{
        "kind": "join",
        "join_type": "left",
        "join_condition": {
            "kind": "binary", "op": "=",
            "left": {"kind": "column", "table": "A", "column": "id"},
            "right": {"kind": "column", "table": "B", "column": "aid"}
        },
        "children": [
            {"kind": "scan", "table_name": "A", "scan_columns": ["id", "x", "z"]},
            {"kind": "scan", "table_name": "B", "scan_columns": ["aid", "y", "w"]}
        ]
    }]
}
write_plan("09_left_join_filter", plan9)


# =============================================================================
# Plan 10: Limit merge (nested limits)
# LIMIT 5 over LIMIT 20 should merge to LIMIT 5
# =============================================================================
plan10 = {
    "kind": "limit",
    "skip": 0,
    "fetch": 5,
    "children": [{
        "kind": "limit",
        "skip": 0,
        "fetch": 20,
        "children": [{
            "kind": "scan",
            "table_name": "data",
            "scan_columns": ["id", "value"]
        }]
    }]
}
write_plan("10_limit_merge", plan10)


# =============================================================================
# Plan 11: Limit with skip + fetch merge
# LIMIT 3 OFFSET 2 over LIMIT 10 OFFSET 5 -> proper merge
# =============================================================================
plan11 = {
    "kind": "limit",
    "skip": 2,
    "fetch": 3,
    "children": [{
        "kind": "limit",
        "skip": 5,
        "fetch": 10,
        "children": [{
            "kind": "scan",
            "table_name": "events",
            "scan_columns": ["id", "ts", "type"]
        }]
    }]
}
write_plan("11_limit_skip_merge", plan11)


# =============================================================================
# Plan 12: Propagate empty through left join (left child empty)
# Empty LEFT JOIN orders -> empty (no left rows to preserve)
# =============================================================================
plan12 = {
    "kind": "join",
    "join_type": "left",
    "join_condition": {
        "kind": "binary", "op": "=",
        "left": {"kind": "column", "table": "empty_t", "column": "id"},
        "right": {"kind": "column", "table": "orders", "column": "oid"}
    },
    "children": [
        {
            "kind": "empty_relation",
            "produce_one_row": False,
            "empty_schema": ["id", "name"]
        },
        {
            "kind": "scan",
            "table_name": "orders",
            "scan_columns": ["oid", "amount"]
        }
    ]
}
write_plan("12_empty_left_join", plan12)


# =============================================================================
# Plan 13: Full outer join where only left is empty -> becomes right side only
# but preserving the schema as a full outer join would (nulls on left side).
# Actually for full outer: left empty -> result is right rows with NULL left cols
# =============================================================================
plan13 = {
    "kind": "join",
    "join_type": "full",
    "join_condition": {
        "kind": "binary", "op": "=",
        "left": {"kind": "column", "table": "empty_t", "column": "id"},
        "right": {"kind": "column", "table": "data", "column": "id"}
    },
    "children": [
        {
            "kind": "empty_relation",
            "produce_one_row": False,
            "empty_schema": ["id", "val"]
        },
        {
            "kind": "scan",
            "table_name": "data",
            "scan_columns": ["id", "val"]
        }
    ]
}
write_plan("13_empty_full_join", plan13)


# =============================================================================
# Plan 14: Complex combined optimization
# SELECT o.amount FROM
#   (SELECT * FROM orders WHERE 1=1) o,
#   (SELECT * FROM customers WHERE active = true) c
# WHERE o.customer_id = c.id
# ORDER BY o.amount DESC
# LIMIT 5
#
# Should: eliminate true filter, convert cross join to inner, push filter, etc.
# =============================================================================
plan14 = {
    "kind": "limit",
    "skip": 0,
    "fetch": 5,
    "children": [{
        "kind": "sort",
        "sort_exprs": [{
            "kind": "sort",
            "sort_expr": {"kind": "column", "table": "o", "column": "amount"},
            "ascending": False,
            "nulls_first": False
        }],
        "children": [{
            "kind": "project",
            "projections": [
                {"kind": "column", "table": "o", "column": "amount"}
            ],
            "children": [{
                "kind": "filter",
                "predicate": {
                    "kind": "binary", "op": "=",
                    "left": {"kind": "column", "table": "o", "column": "customer_id"},
                    "right": {"kind": "column", "table": "c", "column": "id"}
                },
                "children": [{
                    "kind": "join",
                    "join_type": "cross",
                    "join_condition": None,
                    "children": [
                        {
                            "kind": "subquery_alias",
                            "alias_name": "o",
                            "children": [{
                                "kind": "filter",
                                "predicate": {
                                    "kind": "binary", "op": "=",
                                    "left": {"kind": "literal", "value": 1, "dtype": "int"},
                                    "right": {"kind": "literal", "value": 1, "dtype": "int"}
                                },
                                "children": [{
                                    "kind": "scan",
                                    "table_name": "orders",
                                    "scan_columns": ["id", "customer_id", "amount"]
                                }]
                            }]
                        },
                        {
                            "kind": "subquery_alias",
                            "alias_name": "c",
                            "children": [{
                                "kind": "filter",
                                "predicate": {
                                    "kind": "binary", "op": "=",
                                    "left": {"kind": "column", "table": "customers", "column": "active"},
                                    "right": {"kind": "literal", "value": True, "dtype": "bool"}
                                },
                                "children": [{
                                    "kind": "scan",
                                    "table_name": "customers",
                                    "scan_columns": ["id", "name", "active"]
                                }]
                            }]
                        }
                    ]
                }]
            }]
        }]
    }]
}
write_plan("14_combined_complex", plan14)


# =============================================================================
# Plan 15: Filter pushdown through aggregate
# SELECT dept, cnt FROM (SELECT dept, COUNT(*) as cnt FROM emp GROUP BY dept) sub WHERE dept = 'eng'
# The filter on group-by column 'dept' should push below the aggregate.
# =============================================================================
plan15 = {
    "kind": "filter",
    "predicate": {
        "kind": "binary", "op": "=",
        "left": {"kind": "column", "table": "sub", "column": "dept"},
        "right": {"kind": "literal", "value": "eng", "dtype": "string"}
    },
    "children": [{
        "kind": "subquery_alias",
        "alias_name": "sub",
        "children": [{
            "kind": "aggregate",
            "group_by": [{"kind": "column", "table": "emp", "column": "dept"}],
            "aggregates": [
                {
                    "kind": "alias",
                    "alias": "cnt",
                    "expr": {
                        "kind": "agg",
                        "func": "COUNT",
                        "args": [{"kind": "literal", "value": "*", "dtype": "string"}]
                    }
                }
            ],
            "children": [{
                "kind": "scan",
                "table_name": "emp",
                "scan_columns": ["id", "name", "dept", "salary"]
            }]
        }]
    }]
}
write_plan("15_filter_push_aggregate", plan15)


# =============================================================================
# Plan 16: Propagate empty through sort and projection
# Sort(Project(Empty)) should collapse to Empty
# =============================================================================
plan16 = {
    "kind": "sort",
    "sort_exprs": [{
        "kind": "sort",
        "sort_expr": {"kind": "column", "column": "id"},
        "ascending": True
    }],
    "children": [{
        "kind": "project",
        "projections": [
            {"kind": "column", "column": "id"},
            {"kind": "column", "column": "name"}
        ],
        "children": [{
            "kind": "empty_relation",
            "produce_one_row": False,
            "empty_schema": ["id", "name", "extra"]
        }]
    }]
}
write_plan("16_empty_through_sort", plan16)


# =============================================================================
# Plan 17: Right join with empty right child -> empty
# A RIGHT JOIN Empty -> empty (no right rows to drive)
# =============================================================================
plan17 = {
    "kind": "join",
    "join_type": "right",
    "join_condition": {
        "kind": "binary", "op": "=",
        "left": {"kind": "column", "table": "A", "column": "id"},
        "right": {"kind": "column", "table": "empty_t", "column": "id"}
    },
    "children": [
        {"kind": "scan", "table_name": "A", "scan_columns": ["id", "val"]},
        {
            "kind": "empty_relation",
            "produce_one_row": False,
            "empty_schema": ["id", "data"]
        }
    ]
}
write_plan("17_empty_right_join", plan17)


if __name__ == "__main__":
    print(f"Generated {len(os.listdir(PLANS_DIR))} test plans in {PLANS_DIR}")
