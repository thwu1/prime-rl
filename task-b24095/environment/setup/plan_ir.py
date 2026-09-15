"""
Logical query plan intermediate representation (IR) for a simplified SQL engine.

This module defines the node types and expression types used to represent
logical query plans. The optimizer operates on these structures.

"""

from __future__ import annotations
import json
import copy
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class JoinType(Enum):
    INNER = "inner"
    LEFT = "left"
    RIGHT = "right"
    FULL = "full"
    CROSS = "cross"
    LEFT_SEMI = "left_semi"
    LEFT_ANTI = "left_anti"
    RIGHT_SEMI = "right_semi"
    RIGHT_ANTI = "right_anti"


class ExprOp(Enum):
    EQ = "="
    NEQ = "!="
    LT = "<"
    GT = ">"
    LTE = "<="
    GTE = ">="
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    IS_NULL = "IS_NULL"
    IS_NOT_NULL = "IS_NOT_NULL"
    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"
    MOD = "%"


class AggFunc(Enum):
    COUNT = "COUNT"
    SUM = "SUM"
    AVG = "AVG"
    MIN = "MIN"
    MAX = "MAX"
    COUNT_DISTINCT = "COUNT_DISTINCT"


class ScalarFunc(Enum):
    EXTRACT_YEAR = "EXTRACT_YEAR"
    EXTRACT_MONTH = "EXTRACT_MONTH"
    EXTRACT_DAY = "EXTRACT_DAY"
    CAST = "CAST"
    COALESCE = "COALESCE"
    UPPER = "UPPER"
    LOWER = "LOWER"
    LENGTH = "LENGTH"
    ABS = "ABS"
    ROUND = "ROUND"
    CONCAT = "CONCAT"


@dataclass
class Expr:
    """Expression node in the plan tree."""
    kind: str  # "column", "literal", "binary", "unary", "agg", "scalar_func", "alias", "wildcard", "sort"
    # For column
    table: Optional[str] = None
    column: Optional[str] = None
    # For literal
    value: object = None
    dtype: Optional[str] = None  # "int", "float", "string", "bool", "null", "date"
    # For binary op
    op: Optional[str] = None
    left: Optional[Expr] = None
    right: Optional[Expr] = None
    # For unary op
    operand: Optional[Expr] = None
    # For aggregate
    func: Optional[str] = None
    args: Optional[list] = None
    # For scalar function
    scalar_func: Optional[str] = None
    scalar_args: Optional[list] = None
    cast_to: Optional[str] = None
    # For alias
    expr: Optional[Expr] = None
    alias: Optional[str] = None
    # For sort
    sort_expr: Optional[Expr] = None
    ascending: bool = True
    nulls_first: bool = False

    def columns_referenced(self) -> set:
        """Return set of (table, column) tuples referenced."""
        refs = set()
        if self.kind == "column":
            refs.add((self.table, self.column))
        if self.left:
            refs |= self.left.columns_referenced()
        if self.right:
            refs |= self.right.columns_referenced()
        if self.operand:
            refs |= self.operand.columns_referenced()
        if self.args:
            for a in self.args:
                if isinstance(a, Expr):
                    refs |= a.columns_referenced()
        if self.scalar_args:
            for a in self.scalar_args:
                if isinstance(a, Expr):
                    refs |= a.columns_referenced()
        if self.expr:
            refs |= self.expr.columns_referenced()
        if self.sort_expr:
            refs |= self.sort_expr.columns_referenced()
        return refs

    def tables_referenced(self) -> set:
        """Return set of table names referenced."""
        return {t for t, c in self.columns_referenced() if t is not None}

    def is_constant(self) -> bool:
        """Check if expression is a constant (literal or pure computation on literals)."""
        if self.kind == "literal":
            return True
        if self.kind == "binary":
            return (self.left.is_constant() if self.left else True) and (self.right.is_constant() if self.right else True)
        if self.kind == "unary":
            return self.operand.is_constant() if self.operand else True
        return False

    def evaluate_constant(self) -> object:
        """Try to evaluate a constant expression. Returns None if not constant."""
        if not self.is_constant():
            return None
        if self.kind == "literal":
            return self.value
        if self.kind == "binary":
            lv = self.left.evaluate_constant() if self.left else None
            rv = self.right.evaluate_constant() if self.right else None
            if lv is None or rv is None:
                return None
            op = self.op
            if op == "AND":
                return bool(lv) and bool(rv)
            if op == "OR":
                return bool(lv) or bool(rv)
            if op == "=":
                return lv == rv
            if op == "!=":
                return lv != rv
            if op == "<":
                return lv < rv
            if op == ">":
                return lv > rv
            if op == "<=":
                return lv <= rv
            if op == ">=":
                return lv >= rv
        return None

    def is_always_true(self) -> bool:
        if self.is_constant():
            v = self.evaluate_constant()
            return v is True or v == 1
        return False

    def is_always_false(self) -> bool:
        if self.is_constant():
            v = self.evaluate_constant()
            return v is False or v == 0
        return False

    def deep_copy(self) -> Expr:
        return copy.deepcopy(self)

    def __eq__(self, other):
        if not isinstance(other, Expr):
            return False
        return self.to_dict() == other.to_dict()

    def __hash__(self):
        return hash(json.dumps(self.to_dict(), sort_keys=True))

    def to_dict(self) -> dict:
        d = {"kind": self.kind}
        if self.kind == "column":
            if self.table:
                d["table"] = self.table
            d["column"] = self.column
        elif self.kind == "literal":
            d["value"] = self.value
            if self.dtype:
                d["dtype"] = self.dtype
        elif self.kind == "binary":
            d["op"] = self.op
            d["left"] = self.left.to_dict() if self.left else None
            d["right"] = self.right.to_dict() if self.right else None
        elif self.kind == "unary":
            d["op"] = self.op
            d["operand"] = self.operand.to_dict() if self.operand else None
        elif self.kind == "agg":
            d["func"] = self.func
            d["args"] = [a.to_dict() if isinstance(a, Expr) else a for a in (self.args or [])]
        elif self.kind == "scalar_func":
            d["scalar_func"] = self.scalar_func
            d["scalar_args"] = [a.to_dict() if isinstance(a, Expr) else a for a in (self.scalar_args or [])]
            if self.cast_to:
                d["cast_to"] = self.cast_to
        elif self.kind == "alias":
            d["expr"] = self.expr.to_dict() if self.expr else None
            d["alias"] = self.alias
        elif self.kind == "sort":
            d["sort_expr"] = self.sort_expr.to_dict() if self.sort_expr else None
            d["ascending"] = self.ascending
            d["nulls_first"] = self.nulls_first
        elif self.kind == "wildcard":
            if self.table:
                d["table"] = self.table
        return d

    @staticmethod
    def from_dict(d: dict) -> Expr:
        kind = d["kind"]
        e = Expr(kind=kind)
        if kind == "column":
            e.table = d.get("table")
            e.column = d["column"]
        elif kind == "literal":
            e.value = d["value"]
            e.dtype = d.get("dtype")
        elif kind == "binary":
            e.op = d["op"]
            e.left = Expr.from_dict(d["left"]) if d.get("left") else None
            e.right = Expr.from_dict(d["right"]) if d.get("right") else None
        elif kind == "unary":
            e.op = d["op"]
            e.operand = Expr.from_dict(d["operand"]) if d.get("operand") else None
        elif kind == "agg":
            e.func = d["func"]
            e.args = [Expr.from_dict(a) if isinstance(a, dict) else a for a in d.get("args", [])]
        elif kind == "scalar_func":
            e.scalar_func = d["scalar_func"]
            e.scalar_args = [Expr.from_dict(a) if isinstance(a, dict) else a for a in d.get("scalar_args", [])]
            e.cast_to = d.get("cast_to")
        elif kind == "alias":
            e.expr = Expr.from_dict(d["expr"]) if d.get("expr") else None
            e.alias = d.get("alias")
        elif kind == "sort":
            e.sort_expr = Expr.from_dict(d["sort_expr"]) if d.get("sort_expr") else None
            e.ascending = d.get("ascending", True)
            e.nulls_first = d.get("nulls_first", False)
        elif kind == "wildcard":
            e.table = d.get("table")
        return e


@dataclass
class PlanNode:
    """A node in the logical query plan tree."""
    kind: str  # "scan", "filter", "project", "join", "aggregate", "sort", "limit",
                # "union", "distinct", "subquery_alias", "empty_relation", "values"
    # For scan
    table_name: Optional[str] = None
    scan_columns: Optional[list] = None  # list of column names

    # For filter
    predicate: Optional[Expr] = None

    # For project
    projections: Optional[list] = None  # list of Expr

    # For join
    join_type: Optional[str] = None
    join_condition: Optional[Expr] = None  # ON clause
    join_filter: Optional[Expr] = None  # additional filter

    # For aggregate
    group_by: Optional[list] = None  # list of Expr
    aggregates: Optional[list] = None  # list of Expr (agg kind)

    # For sort
    sort_exprs: Optional[list] = None  # list of Expr (sort kind)

    # For limit
    skip: int = 0
    fetch: Optional[int] = None

    # For subquery alias
    alias_name: Optional[str] = None

    # For empty relation
    produce_one_row: bool = False
    empty_schema: Optional[list] = None  # list of column name strings

    # For values
    values_data: Optional[list] = None  # list of list of Expr (rows)
    values_schema: Optional[list] = None  # list of column names

    # Children
    children: list = field(default_factory=list)  # list of PlanNode

    @property
    def left(self) -> Optional[PlanNode]:
        return self.children[0] if self.children else None

    @property
    def right(self) -> Optional[PlanNode]:
        return self.children[1] if len(self.children) > 1 else None

    def output_columns(self) -> list:
        """Return list of (table, column) tuples this node outputs."""
        if self.kind == "scan":
            cols = self.scan_columns or []
            return [(self.table_name, c) for c in cols]
        elif self.kind == "filter":
            return self.children[0].output_columns() if self.children else []
        elif self.kind == "project":
            result = []
            for p in (self.projections or []):
                if p.kind == "column":
                    result.append((p.table, p.column))
                elif p.kind == "alias":
                    result.append((None, p.alias))
                elif p.kind == "wildcard":
                    if self.children:
                        result.extend(self.children[0].output_columns())
                else:
                    result.append((None, str(id(p))))
            return result
        elif self.kind == "join":
            left_cols = self.children[0].output_columns() if self.children else []
            right_cols = self.children[1].output_columns() if len(self.children) > 1 else []
            jt = self.join_type or "inner"
            if jt in ("left_semi", "left_anti"):
                return left_cols
            if jt in ("right_semi", "right_anti"):
                return right_cols
            return left_cols + right_cols
        elif self.kind == "aggregate":
            result = []
            for g in (self.group_by or []):
                if g.kind == "column":
                    result.append((g.table, g.column))
                elif g.kind == "alias":
                    result.append((None, g.alias))
                else:
                    result.append((None, str(id(g))))
            for a in (self.aggregates or []):
                if a.kind == "alias":
                    result.append((None, a.alias))
                else:
                    result.append((None, str(id(a))))
            return result
        elif self.kind == "sort":
            return self.children[0].output_columns() if self.children else []
        elif self.kind == "limit":
            return self.children[0].output_columns() if self.children else []
        elif self.kind == "union":
            return self.children[0].output_columns() if self.children else []
        elif self.kind == "distinct":
            return self.children[0].output_columns() if self.children else []
        elif self.kind == "subquery_alias":
            child_cols = self.children[0].output_columns() if self.children else []
            return [(self.alias_name, c) for _, c in child_cols]
        elif self.kind == "empty_relation":
            return [(None, c) for c in (self.empty_schema or [])]
        elif self.kind == "values":
            return [(None, c) for c in (self.values_schema or [])]
        return []

    def is_empty_relation(self) -> bool:
        return self.kind == "empty_relation" and not self.produce_one_row

    def deep_copy(self) -> PlanNode:
        return copy.deepcopy(self)

    def child_tables(self) -> set:
        """Recursively collect all table names from scan nodes."""
        tables = set()
        if self.kind == "scan" and self.table_name:
            tables.add(self.table_name)
        for c in self.children:
            tables |= c.child_tables()
        return tables

    def to_dict(self) -> dict:
        d = {"kind": self.kind}
        if self.kind == "scan":
            d["table_name"] = self.table_name
            if self.scan_columns:
                d["scan_columns"] = self.scan_columns
        elif self.kind == "filter":
            d["predicate"] = self.predicate.to_dict() if self.predicate else None
        elif self.kind == "project":
            d["projections"] = [p.to_dict() for p in (self.projections or [])]
        elif self.kind == "join":
            d["join_type"] = self.join_type
            d["join_condition"] = self.join_condition.to_dict() if self.join_condition else None
            if self.join_filter:
                d["join_filter"] = self.join_filter.to_dict()
        elif self.kind == "aggregate":
            d["group_by"] = [g.to_dict() for g in (self.group_by or [])]
            d["aggregates"] = [a.to_dict() for a in (self.aggregates or [])]
        elif self.kind == "sort":
            d["sort_exprs"] = [s.to_dict() for s in (self.sort_exprs or [])]
        elif self.kind == "limit":
            d["skip"] = self.skip
            d["fetch"] = self.fetch
        elif self.kind == "subquery_alias":
            d["alias_name"] = self.alias_name
        elif self.kind == "empty_relation":
            d["produce_one_row"] = self.produce_one_row
            d["empty_schema"] = self.empty_schema
        elif self.kind == "values":
            d["values_data"] = [[v.to_dict() for v in row] for row in (self.values_data or [])]
            d["values_schema"] = self.values_schema
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d

    @staticmethod
    def from_dict(d: dict) -> PlanNode:
        kind = d["kind"]
        node = PlanNode(kind=kind)
        if kind == "scan":
            node.table_name = d.get("table_name")
            node.scan_columns = d.get("scan_columns")
        elif kind == "filter":
            node.predicate = Expr.from_dict(d["predicate"]) if d.get("predicate") else None
        elif kind == "project":
            node.projections = [Expr.from_dict(p) for p in d.get("projections", [])]
        elif kind == "join":
            node.join_type = d.get("join_type")
            node.join_condition = Expr.from_dict(d["join_condition"]) if d.get("join_condition") else None
            node.join_filter = Expr.from_dict(d["join_filter"]) if d.get("join_filter") else None
        elif kind == "aggregate":
            node.group_by = [Expr.from_dict(g) for g in d.get("group_by", [])]
            node.aggregates = [Expr.from_dict(a) for a in d.get("aggregates", [])]
        elif kind == "sort":
            node.sort_exprs = [Expr.from_dict(s) for s in d.get("sort_exprs", [])]
        elif kind == "limit":
            node.skip = d.get("skip", 0)
            node.fetch = d.get("fetch")
        elif kind == "subquery_alias":
            node.alias_name = d.get("alias_name")
        elif kind == "empty_relation":
            node.produce_one_row = d.get("produce_one_row", False)
            node.empty_schema = d.get("empty_schema")
        elif kind == "values":
            node.values_data = [[Expr.from_dict(v) for v in row] for row in d.get("values_data", [])]
            node.values_schema = d.get("values_schema")
        node.children = [PlanNode.from_dict(c) for c in d.get("children", [])]
        return node

    def display(self, indent=0) -> str:
        prefix = "  " * indent
        parts = [f"{prefix}{self.kind}"]
        if self.kind == "scan":
            parts[0] += f" table={self.table_name}"
            if self.scan_columns:
                parts[0] += f" cols={self.scan_columns}"
        elif self.kind == "filter":
            parts[0] += f" pred={_expr_str(self.predicate)}"
        elif self.kind == "project":
            exprs = ", ".join(_expr_str(p) for p in (self.projections or []))
            parts[0] += f" [{exprs}]"
        elif self.kind == "join":
            parts[0] += f" type={self.join_type}"
            if self.join_condition:
                parts[0] += f" on={_expr_str(self.join_condition)}"
            if self.join_filter:
                parts[0] += f" filter={_expr_str(self.join_filter)}"
        elif self.kind == "aggregate":
            gb = ", ".join(_expr_str(g) for g in (self.group_by or []))
            ag = ", ".join(_expr_str(a) for a in (self.aggregates or []))
            parts[0] += f" group_by=[{gb}] aggs=[{ag}]"
        elif self.kind == "sort":
            exprs = ", ".join(_expr_str(s) for s in (self.sort_exprs or []))
            parts[0] += f" [{exprs}]"
        elif self.kind == "limit":
            parts[0] += f" skip={self.skip} fetch={self.fetch}"
        elif self.kind == "subquery_alias":
            parts[0] += f" alias={self.alias_name}"
        elif self.kind == "empty_relation":
            parts[0] += f" one_row={self.produce_one_row}"
        for c in self.children:
            parts.append(c.display(indent + 1))
        return "\n".join(parts)


def _expr_str(e: Expr) -> str:
    if e is None:
        return "None"
    if e.kind == "column":
        if e.table:
            return f"{e.table}.{e.column}"
        return e.column
    if e.kind == "literal":
        return repr(e.value)
    if e.kind == "binary":
        return f"({_expr_str(e.left)} {e.op} {_expr_str(e.right)})"
    if e.kind == "unary":
        return f"({e.op} {_expr_str(e.operand)})"
    if e.kind == "agg":
        args = ", ".join(_expr_str(a) for a in (e.args or []))
        return f"{e.func}({args})"
    if e.kind == "scalar_func":
        args = ", ".join(_expr_str(a) for a in (e.scalar_args or []))
        return f"{e.scalar_func}({args})"
    if e.kind == "alias":
        return f"{_expr_str(e.expr)} AS {e.alias}"
    if e.kind == "sort":
        direction = "ASC" if e.ascending else "DESC"
        return f"{_expr_str(e.sort_expr)} {direction}"
    if e.kind == "wildcard":
        if e.table:
            return f"{e.table}.*"
        return "*"
    return f"<{e.kind}>"


def load_plan(path: str) -> PlanNode:
    with open(path) as f:
        return PlanNode.from_dict(json.load(f))


def save_plan(plan: PlanNode, path: str):
    with open(path, "w") as f:
        json.dump(plan.to_dict(), f, indent=2)


# Utility functions for building expressions
def col(name: str, table: str = None) -> Expr:
    return Expr(kind="column", column=name, table=table)

def lit(value, dtype: str = None) -> Expr:
    if dtype is None:
        if isinstance(value, bool):
            dtype = "bool"
        elif isinstance(value, int):
            dtype = "int"
        elif isinstance(value, float):
            dtype = "float"
        elif isinstance(value, str):
            dtype = "string"
        elif value is None:
            dtype = "null"
    return Expr(kind="literal", value=value, dtype=dtype)

def binary(op: str, left: Expr, right: Expr) -> Expr:
    return Expr(kind="binary", op=op, left=left, right=right)

def and_expr(left: Expr, right: Expr) -> Expr:
    return binary("AND", left, right)

def or_expr(left: Expr, right: Expr) -> Expr:
    return binary("OR", left, right)

def conjunction(exprs: list) -> Optional[Expr]:
    """Combine a list of expressions with AND. Returns None if list is empty."""
    if not exprs:
        return None
    result = exprs[0]
    for e in exprs[1:]:
        result = and_expr(result, e)
    return result

def split_conjunction(expr: Expr) -> list:
    """Split an AND-connected expression into a list of conjuncts."""
    if expr.kind == "binary" and expr.op == "AND":
        return split_conjunction(expr.left) + split_conjunction(expr.right)
    return [expr]
